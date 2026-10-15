"""The whole life of a switch against a simulated Telegram account and a fast-forwarded clock:
check-ins, escalation, silence and panic triggers, scheduling, backups, auto-reply, abort, rehearsal
and the requests the menu sends over SSH."""

import asyncio
import shutil
import time

import pytest

from helpers import push_locally, write_meta
from phoenix.account import ScheduleRejected
from phoenix.crypto import Crypto
from phoenix.db import Store
from phoenix.engine import Engine
from phx.core import Failed

D = 86400


class FakeAccount:
    def __init__(self, clock, calls):
        self.clock, self.calls = clock, calls
        self.about, self.reject, self.read = "old bio", set(), False

    async def health(self):
        return True, "fake ok"

    async def resolve(self, ref):
        return {"@mom": 1, "@friend": 2, "@bro": 3, "@group": 4}[ref], f"user {ref}"

    async def input_peer(self, user_id):
        return user_id

    async def send(self, peer, *, text=None, path=None, kind="file", schedule=None):
        if schedule and peer in self.reject:
            raise ScheduleRejected("too much")
        what = text[:25] if text else f"{kind}:{path.name}"
        self.calls.append(("send", peer, what, None if schedule is None else round((schedule - self.clock[0]) / D)))
        return [len(self.calls)]

    async def delete_scheduled(self, peer, ids):
        self.calls.append(("delete_scheduled", peer, ids))

    async def was_read(self, user_id, since):
        return self.read

    async def set_about(self, text):
        previous, self.about = self.about, text
        return previous


@pytest.fixture
def packages(tmp_path):
    pk = tmp_path / "packages"
    m = pk / "mom"
    write_meta(m, name="Mom", telegram="@mom", backup="@bro")
    (m / "01-letter.txt").write_text("Hi mom")
    (m / "02-voice.ogg").write_bytes(b"ogg")
    (m / "03-hug.round.mp4").write_bytes(b"mp4")
    (m / "04-photo.jpg").write_bytes(b"jpg")
    for folder, name, text in [("@+1y", "birthday.txt", "Happy birthday in a year"),
                               ("@+2y", "later.txt", "Two years later"),
                               ("@2020-01-01", "past.txt", "past date -> right away")]:
        (m / folder).mkdir()
        (m / folder / name).write_text(text)
    f = pk / "friend"
    write_meta(f, name="Friend", telegram="@friend", on=["panic"], delay=3 * D)
    (f / "01-letter.txt").write_text("Friend letter")
    (pk / "_account.toml").write_text('on=["silence"]\nautoreply="I am gone."\nabout="In memory"\n'
                                      '[[post]]\nchat="@group"\ntext="Goodbye all"\n')
    return pk


def test_bad_schedule_folder_is_rejected(server, packages):
    _, public_key, data = server
    (packages / "mom" / "@soon").mkdir()
    (packages / "mom" / "@soon" / "x.txt").write_text("x")
    with pytest.raises(Failed, match="@soon"):
        push_locally(packages, public_key, data)
    shutil.rmtree(packages / "mom" / "@soon")
    push_locally(packages, public_key, data)


def test_full_lifecycle(server, packages, monkeypatch):
    cfg, public_key, data = server
    push_locally(packages, public_key, data)

    clock, calls, notes = [time.time()], [], []
    monkeypatch.setattr(time, "time", lambda: clock[0])
    account = FakeAccount(clock, calls)

    async def notify(text, keyboard=None):
        notes.append(text)

    store = Store(cfg.db_path)
    engine = Engine(cfg, store, account, Crypto(cfg.identity_path), notify)

    async def step(days=0.0):
        clock[0] += days * D
        await engine.tick()
        if engine._task:
            await engine._task

    def sends():
        return [c for c in calls if c[0] == "send"]

    async def scenario():
        store.set("last_checkin", clock[0])
        store.set("phase", "armed")
        await step()
        assert "Packages updated" in notes[-1] and "❌" not in notes[-1], notes[-1]

        # Telegram activity postpones the deadline, but the button is still needed every 30 days.
        for _ in range(6):
            clock[0] += 5 * D
            engine.on_activity()
            await engine.tick()
        assert store.get("phase") == "overdue" and "button check-in is needed" in notes[-1]
        engine.checkin()

        # Review reminder after 90 days without changes.
        store.set("pkg_updated_at", clock[0] - 91 * D)
        await engine.tick()
        assert "last updated" in notes[-1]
        engine.review_ack()
        engine.checkin()

        # Silence: reminders, alarm, then delivery.
        calls.clear()
        await step(14.01)
        assert store.get("phase") == "alarm"
        await step(7.01)
        assert store.get("phase") == "triggered"
        assert all(c[1] != 2 for c in sends()), "the friend's package is panic-only"
        assert account.about == "In memory"
        assert not any("Two years" in c[2] or "birthday" in c[2] for c in sends()), "items over a year away wait"
        assert any(c[1] == 4 and "Goodbye" in c[2] for c in sends()), "post"
        assert store.get("waiting") == 2

        calls.clear()
        await step(1.01)
        assert ("send", 1, "Happy birthday in a year", 364) in calls, calls

        # Auto-reply: once per person, never to recipients.
        await engine.autoreply(555, 555)
        await engine.autoreply(555, 555)
        await engine.autoreply(1, 1)
        assert [c for c in sends() if c[2].startswith("I am gone")] == [("send", 555, "I am gone.", None)]

        # Unread after 7 days: the backup person gets the same package with a note.
        calls.clear()
        await step(6.01)
        to_backup = [c for c in calls if c[1] == 3]
        assert to_backup and "meant for Mom" in to_backup[0][2]

        calls.clear()
        await step(375)
        assert store.get("phase") == "done"

        # Re-arm; panic schedules the friend's package +3d; abort cancels it.
        await engine.rearm()
        assert account.about == "old bio"
        calls.clear()
        engine.panic()
        await step(1 / 24 + 0.001)
        assert any(c[1] == 2 and c[3] == 3 for c in sends())
        assert account.about == "old bio", "account actions are silence-only"
        await engine.abort()
        assert {c[1] for c in calls if c[0] == "delete_scheduled"} == {2}
        assert store.get("phase") == "armed"

        # Telegram refuses to schedule: the server keeps it and sends at the due time itself.
        account.reject = {2}
        calls.clear()
        engine.panic()
        await step(1 / 24 + 0.001)
        assert store.get("waiting") >= 1
        await step(3.01)
        assert any(c[1] == 2 and c[3] is None and "Friend" in c[2] for c in calls)
        await engine.abort()

        # Rehearsal: everything goes to Saved Messages.
        calls.clear()
        engine.start_test()
        await engine._task
        assert sends() and all(c[1] == "me" for c in sends())

        # Requests from the menu (ctl over SSH) reach the running engine.
        from phoenix import ctl

        serving = asyncio.create_task(engine._serve_requests())
        answer = await asyncio.to_thread(lambda: ctl.request(Store(cfg.db_path), "verify"))
        assert "Mom" in answer and "Friend" in answer
        answer = await asyncio.to_thread(lambda: ctl.request(Store(cfg.db_path), "health"))
        assert "fake ok" in answer
        assert ctl.summary(store, 2)["phase"] == "armed"
        serving.cancel()

    asyncio.run(scenario())

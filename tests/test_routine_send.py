"""P44-2: ``ChatService.send_for_routine``: the message a run sends is the same send as a person's (every limit, every question about a
command or a file, the day's money), only into the chat a run is in the middle of opening, never with an ``origin``, and not
reachable from the browser's routes."""
from __future__ import annotations

import inspect
import unittest

from tests.routine_fixtures import RoutineBase
from vbear import routines as rt, server
from vbear.api_error import ApiError


class SendForRoutineTests(RoutineBase):
    def open_chat(self, profile=None, slot="2026-11-09T08:00", state="starting"):
        routine = self.routine()
        chat_id = self.service.create({"profile_id": profile or self.writer})["chat"]["id"]
        run = rt.new_run(routine["id"], slot, state="waiting", why="on_time", now=self.now[0])
        rt.update_run(run["run_id"], ("waiting",), now=self.now[0], state=state, by="you", chat_id=chat_id)
        return chat_id, run

    def test_it_sends_into_the_chat_of_a_run_that_is_starting_with_no_origin(self):
        chat_id, _ = self.open_chat()
        out = self.service.send_for_routine(chat_id, "整理好了嗎？")
        self.assertEqual(out["turn"], 1)
        self.assertEqual(len(self.sent()), 1)
        self.assertNotIn("origin", self.sent()[0], "the chat's record gets no new field")
        self.assertEqual(self.sent()[0]["text"], "整理好了嗎？")

    def test_it_refuses_a_chat_no_run_is_opening(self):
        solo = self.service.create({"profile_id": self.writer})["chat"]["id"]
        with self.assertRaises(ApiError) as ctx:
            self.service.send_for_routine(solo, "這不是例行工作的聊天")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(self.sent(), [])

    def test_it_refuses_a_chat_whose_run_has_moved_on_or_never_started(self):
        chat_id, run = self.open_chat(state="running")
        with self.assertRaises(ApiError):
            self.service.send_for_routine(chat_id, "第二則")
        self.assertEqual(self.sent(), [])

    def test_it_refuses_what_is_not_text_or_is_empty(self):
        chat_id, _ = self.open_chat()
        for bad in (None, 5, ["x"]):
            with self.assertRaises(ApiError):
                self.service.send_for_routine(chat_id, bad)
        with self.assertRaises(ApiError):
            self.service.send_for_routine(chat_id, "   ")
        self.assertEqual(self.sent(), [])

    def test_the_daemon_still_has_the_last_word(self):
        chat_id, _ = self.open_chat()
        self.daemon.refuse = ["red"]
        with self.assertRaises(ApiError) as ctx:
            self.service.send_for_routine(chat_id, "今天額度用完了")
        self.assertEqual(ctx.exception.code, "red")
        self.assertEqual(self.sent(), [])

    def test_the_browsers_send_has_no_way_to_name_a_routine_and_the_routes_do_not_call_it(self):
        self.assertEqual(list(inspect.signature(self.service.send).parameters), ["chat_id", "body"])
        source = inspect.getsource(server)
        self.assertNotIn("send_for_routine", source)

    def test_a_person_can_go_on_in_a_chat_a_run_opened_once_it_has_its_turn(self):
        chat_id, run = self.open_chat()
        self.service.send_for_routine(chat_id, "第一則")
        rt.update_run(run["run_id"], ("starting",), now=self.now[0], state="running", turn=1)
        self.daemon.finish(chat_id, reply="好了")
        self.assertEqual(self.service.send(chat_id, {"text": "再補一句"})["turn"], 2, "that is an ordinary chat now")


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the structured fault ticket and its clarification gate."""

import unittest

from printcare.assistant.fault_ticket import FaultTicket, update_ticket
from printcare.assistant.prompts import build_messages


class FaultTicketExtractionTest(unittest.TestCase):
    def test_example_description_becomes_ticket(self):
        ticket = update_ticket(
            None,
            "打印时不出料，已经重新装料，未解决",
            "a1_mini",
        )

        self.assertEqual(ticket.machine, "a1_mini")
        self.assertEqual(ticket.symptom, "打印时不出料")
        self.assertIsNone(ticket.error_code)
        self.assertIsNone(ticket.filament)
        self.assertIsNone(ticket.feed_method)
        self.assertEqual(ticket.stage, "打印中")
        self.assertEqual(ticket.attempted_steps, ("重新装料（未解决）",))
        self.assertEqual(ticket.flow, "no_extrusion")
        self.assertEqual(ticket.missing_information(), ("error_code", "feed_method"))

    def test_extracts_filament_feed_method_error_and_stage(self):
        ticket = update_ticket(
            None,
            "A1 mini 使用外置料架，PLA，打印中不出料，错误码 0300-1000-0002-0001",
            "a1_mini",
        )

        self.assertEqual(ticket.filament, "PLA")
        self.assertEqual(ticket.feed_method, "外置料架")
        self.assertEqual(ticket.error_code, "0300_1000_0002_0001")
        self.assertEqual(ticket.stage, "打印中")
        self.assertEqual(ticket.flow, "hms")

    def test_ams_lite_is_distinguished_from_external_spool(self):
        ticket = update_ticket(None, "AMS lite 供料，打印时不出料", "a1")

        self.assertEqual(ticket.feed_method, "AMS lite")
        self.assertEqual(ticket.flow, "no_extrusion")

    def test_unknown_feed_method_is_recorded_without_repeating(self):
        ticket = update_ticket(None, "不知道用的什么供料，打印时不出料", "a1")

        self.assertEqual(ticket.feed_method, "未知")
        self.assertNotIn("feed_method", ticket.clarification_fields())

    def test_followup_merges_into_previous_ticket(self):
        first = update_ticket(None, "打印时不出料", "a1_mini")
        second = update_ticket(first, "使用外置料架，没有错误码", "a1_mini")

        self.assertEqual(second.symptom, "打印时不出料")
        self.assertEqual(second.feed_method, "外置料架")
        self.assertEqual(second.error_code, "无")
        self.assertEqual(second.flow, "no_extrusion")

    def test_detailed_maintenance_request_is_not_gated(self):
        ticket = update_ticket(None, "挤出机堵料怎么清理？", "a1")

        self.assertEqual(ticket.flow, "clog")
        self.assertFalse(ticket.should_clarify("挤出机堵料怎么清理？"))

    def test_vague_no_extrusion_asks_branch_questions_only(self):
        ticket = update_ticket(None, "A1 打印时不出料", "a1")

        self.assertTrue(ticket.should_clarify("A1 打印时不出料"))
        self.assertEqual(ticket.clarification_fields(), ("error_code", "feed_method"))
        text = ticket.clarification_text()
        self.assertIn("错误码", text)
        self.assertIn("AMS lite", text)
        self.assertNotIn("什么耗材", text)

    def test_asked_fields_are_not_repeated(self):
        ticket = update_ticket(None, "A1 打印时不出料", "a1")
        asked = ticket.mark_asked()

        self.assertFalse(asked.should_clarify("A1 打印时不出料"))
        self.assertTrue(asked.asked)

    def test_machine_change_resets_ticket(self):
        ticket = update_ticket(None, "A1 打印时不出料", "a1")
        switched = update_ticket(ticket, "A1 mini 热床不升温", "a1_mini")

        self.assertEqual(switched.machine, "a1_mini")
        self.assertEqual(switched.symptom, "热床不升温")
        self.assertEqual(switched.flow, "heatbed")
        self.assertIsNone(switched.feed_method)

    def test_prompt_stops_asking_after_key_fields(self):
        ticket = update_ticket(None, "A1 打印时不出料", "a1").mark_asked()
        messages = build_messages("使用外置料架，没有错误码", "a1", [], None, ticket)

        self.assertIn("不要再追问耗材", messages[1]["content"])

    def test_serialization_round_trip(self):
        ticket = update_ticket(None, "A1 热床不升温，已经断电", "a1")
        restored = FaultTicket.from_dict(ticket.to_dict())

        self.assertEqual(restored, ticket)


if __name__ == "__main__":
    unittest.main()

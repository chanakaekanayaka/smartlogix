"""
Unit tests for the deterministic refund rules and the reply consistency guard.
No LLM or network calls - run with:

    python -m unittest discover -s tests -v
"""

import unittest
from unittest.mock import patch

from src.agents.decision_rules import (
    check_reply_consistency, decide, decision_statement, template_reply,
)
from src.agents.schemas import IntakeOutput, InvestigationOutput, PolicyOutput


class DecideTests(unittest.TestCase):
    def test_late_order_with_packaging_fault_is_partial_not_full(self):
        # The original bug: a late order hit the "warehouse" row and got a full refund.
        self.assertEqual(decide("late", "warehouse").action, "partial_refund")
        self.assertEqual(decide("late", "courier").action, "partial_refund")

    def test_damaged_by_warehouse_or_courier_is_full_refund(self):
        self.assertEqual(decide("damaged", "warehouse").action, "full_refund")
        self.assertEqual(decide("damaged", "courier").action, "full_refund")

    def test_weather_is_no_refund_per_policy(self):
        self.assertEqual(decide("damaged", "weather").action, "no_refund")
        self.assertEqual(decide("late", "weather").action, "no_refund")

    def test_unclear_and_unknown_cases_escalate(self):
        for issue, fault in [("damaged", "unclear"), ("late", "unclear"),
                             ("lost", "weather"), ("other", "courier"), (None, None)]:
            decision = decide(issue, fault)
            self.assertEqual(decision.action, "escalated_to_human", (issue, fault))
            self.assertTrue(decision.escalate_to_human)

    def test_policy_question_is_information_only(self):
        self.assertEqual(decide("policy_question", None).action, "information_only")

    def test_every_decision_cites_a_policy(self):
        for issue in ["damaged", "late", "lost", "wrong_address", "other"]:
            for fault in ["courier", "warehouse", "customer", "weather", "unclear"]:
                self.assertTrue(decide(issue, fault).policy_basis)


class ConsistencyGuardTests(unittest.TestCase):
    def test_reply_from_original_bug_is_rejected(self):
        # Real reply logged for ORD10008 (late): decision was full_refund but text said 50%.
        reply = ("We're sorry for the delay on ORD10008. You are eligible for a "
                 "50 % partial refund of the delivery fee.")
        self.assertTrue(check_reply_consistency("full_refund", "late", reply))

    def test_matching_partial_refund_reply_passes(self):
        reply = "Sorry for the delay. You will receive a refund of 50% of the delivery fee."
        self.assertEqual(check_reply_consistency("partial_refund", "late", reply), [])

    def test_partial_refund_reply_promising_full_refund_is_rejected(self):
        reply = "You will receive a full refund of 50% of the delivery fee."
        self.assertTrue(check_reply_consistency("partial_refund", "late", reply))

    def test_reply_must_state_the_decision(self):
        self.assertTrue(check_reply_consistency("full_refund", "damaged", "We are sorry."))

    def test_damage_escalation_may_mention_25_percent(self):
        reply = "A human support agent will review this. A temporary 25% refund is offered."
        self.assertEqual(check_reply_consistency("escalated_to_human", "damaged", reply), [])
        self.assertTrue(check_reply_consistency("escalated_to_human", "late", reply))

    def test_no_refund_reply_must_not_offer_money(self):
        self.assertTrue(check_reply_consistency("no_refund", "late", "No refund, but here is 10% off."))
        self.assertEqual(check_reply_consistency(
            "no_refund", "late", "Under our policy, no refund applies in this case."), [])

    def test_invented_processing_time_is_rejected(self):
        # Seen in the live app: the LLM promised "3-5 business days" (policy says 5-7).
        reply = "You will receive a full refund within 3‑5 business days."
        self.assertTrue(check_reply_consistency("full_refund", "damaged", reply))
        reply = "You will receive a full refund within 5-7 working days."
        self.assertEqual(check_reply_consistency("full_refund", "damaged", reply), [])

    def test_template_reply_is_always_consistent(self):
        for issue in ["damaged", "late", "lost", "wrong_address", "other"]:
            for fault in ["courier", "warehouse", "customer", "weather", "unclear"]:
                decision = decide(issue, fault)
                reply = template_reply("ORD10001", issue, fault, decision)
                self.assertEqual(check_reply_consistency(decision.action, issue, reply), [],
                                 (issue, fault, reply))

    def test_decision_statement_is_always_consistent(self):
        for issue in ["damaged", "late", "lost"]:
            for fault in ["courier", "warehouse", "weather", "unclear"]:
                decision = decide(issue, fault)
                statement = decision_statement(issue, decision)
                self.assertEqual(check_reply_consistency(decision.action, issue, statement), [])


class ResolutionAgentTests(unittest.TestCase):
    """run_resolution_agent with the LLM and audit log mocked out."""

    def _run(self, llm_reply=None, llm_error=None):
        from src.agents import resolution_agent

        intake = IntakeOutput(status="ok", order_id="ORD10008", issue_type="late",
                              summary="Order is late")
        investigation = InvestigationOutput(order_id="ORD10008", order_found=True,
                                            likely_fault="warehouse", confidence=0.9,
                                            reasoning="Packaging label mismatch.")
        policy = PolicyOutput(answer="...", sources=["01_refund_policy.md"], chunks=[])
        with patch.object(resolution_agent, "call_llm",
                          side_effect=llm_error, return_value=llm_reply), \
             patch.object(resolution_agent, "log_agent_event"):
            return resolution_agent.run_resolution_agent(intake, investigation, policy, "test")

    def test_contradicting_llm_reply_falls_back_to_template(self):
        result = self._run(llm_reply="Good news - you will get a full refund!")
        self.assertEqual(result.action, "partial_refund")
        self.assertEqual(result.reply_source, "template")
        self.assertIn("50%", result.final_answer)
        self.assertNotIn("full refund", result.final_answer.lower())

    def test_consistent_llm_reply_is_kept(self):
        reply = "Sorry for the delay. You will receive a refund of 50% of the delivery fee."
        result = self._run(llm_reply=reply)
        self.assertEqual(result.reply_source, "llm")
        self.assertEqual(result.final_answer, reply)

    def test_llm_failure_still_returns_a_reply(self):
        result = self._run(llm_error=RuntimeError("rate limited"))
        self.assertEqual(result.reply_source, "template")
        self.assertIn("50%", result.final_answer)


if __name__ == "__main__":
    unittest.main()

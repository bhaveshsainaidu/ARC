"""
tests/test_specialized_agents.py — Unit tests for ARC v2.0 Specialized Agents & Gesture Control.

Verifies:
- Section 6: actions/gesture_control.py
- Section 12 Agent 1: actions/research_agent.py
- Section 12 Agent 2: actions/document_intelligence.py
- Section 12 Agent 3: actions/fact_checker.py
- Section 12 Agent 4: actions/complaint_triage.py
- Section 12 Agent 5: actions/network_diagnosis.py
- Section 12 Agent 6: actions/procurement_agent.py
- Section 12 Agent 7: actions/reproducibility_agent.py
- Section 12 Agent 8: actions/compliance_tracker.py
- Section 12 Agent 9: actions/pattern_risk_agent.py
- Section 12 Agent 10: plugins/permission_auditor.py
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class TestSpecializedAgents(unittest.TestCase):

    # ── Section 6: Gesture Control ───────────────────────────────────────────
    def test_gesture_control(self):
        from actions.gesture_control import TOOL, gesture_control, GestureController

        self.assertEqual(TOOL["name"], "gesture_control")
        self.assertIn("action", TOOL["parameters"]["properties"])

        # Status check
        res = gesture_control({"action": "status"})
        self.assertIn("Gesture Control Status", res)
        self.assertIn("Recognized gestures", res)

        # Start and stop
        ctrl = GestureController.get_instance()
        ok, msg = ctrl.stop()
        self.assertTrue(ok)
        self.assertFalse(ctrl.is_running())

    # ── Agent 1: Research Agent ──────────────────────────────────────────────
    def test_research_agent(self):
        from actions.research_agent import TOOL, _format_apa, _format_bibtex

        self.assertEqual(TOOL["name"], "research_agent")
        self.assertIn("query", TOOL["parameters"]["properties"])

        paper = {
            "title": "Attention Is All You Need",
            "authors": ["Vaswani, A.", "Shazeer, N."],
            "year": "2017",
            "url": "https://arxiv.org/abs/1706.03762",
            "id": "1706.03762",
        }
        apa = _format_apa(paper)
        self.assertIn("Vaswani, A.", apa)
        self.assertIn("(2017)", apa)

        bib = _format_bibtex(paper)
        self.assertIn("@article{", bib)
        self.assertIn("Attention Is All You Need", bib)

    # ── Agent 2: Document Intelligence ───────────────────────────────────────
    def test_document_intelligence(self):
        from actions.document_intelligence import TOOL, document_intelligence, _extract_clauses, _audit_standard_protections

        self.assertEqual(TOOL["name"], "document_intelligence")
        sample_contract = (
            "1. Termination & Liabilities.\n"
            "Either party may terminate this agreement for convenience upon 30 days notice. "
            "The vendor shall indemnify and hold harmless the client against all liabilities without limitation.\n\n"
            "2. Governing Law.\n"
            "This agreement is governed by the laws of the State of California. "
            "The aggregate liability of either party shall not exceed the total fees paid in the preceding 12 months."
        )

        clauses = _extract_clauses(sample_contract)
        self.assertTrue(len(clauses) >= 1)

        audit = _audit_standard_protections(sample_contract)
        self.assertTrue(audit["Limitation of Liability"])
        self.assertTrue(audit["Governing Law & Jurisdiction"])
        self.assertFalse(audit["Force Majeure"])

        report = document_intelligence({"text": sample_contract})
        self.assertIn("ARC Document Intelligence Review", report)
        self.assertIn("Missing Protections Audit", report)

    # ── Agent 3: Fact Checker ────────────────────────────────────────────────
    def test_fact_checker(self):
        from actions.fact_checker import TOOL, fact_checker, _heuristic_verification

        self.assertEqual(TOOL["name"], "fact_checker")
        self.assertIn("claim", TOOL["parameters"]["properties"])

        mock_evidence = [
            {
                "source": "Wikipedia",
                "title": "Speed of light",
                "snippet": "The speed of light in vacuum is exactly 299,792,458 metres per second.",
                "url": "https://en.wikipedia.org/wiki/Speed_of_light",
                "credibility": 0.95,
            }
        ]
        report = _heuristic_verification("Light travels at approximately 300,000 km/s in vacuum.", mock_evidence)
        self.assertIn("Evidence Overview", report)
        self.assertIn("Speed of light", report)

    # ── Agent 4: Complaint Triage ────────────────────────────────────────────
    def test_complaint_triage(self):
        from actions.complaint_triage import TOOL, complaint_triage, _triage_ticket

        self.assertEqual(TOOL["name"], "complaint_triage")
        raw_tickets = [
            {"id": "TCK-101", "text": "Production system is down! 500 internal server error on checkout!", "tier": "Enterprise"},
            {"id": "TCK-102", "text": "I was overcharged on my credit card invoice last month.", "tier": "Standard"},
            {"id": "TCK-103", "text": "Would love if you could add a dark mode theme option.", "tier": "Standard"},
        ]

        t1 = _triage_ticket(raw_tickets[0])
        self.assertEqual(t1["department"], "Engineering / Bug")
        self.assertIn("P0", t1["priority"])

        t2 = _triage_ticket(raw_tickets[1])
        self.assertEqual(t2["department"], "Billing & Commercial")

        t3 = _triage_ticket(raw_tickets[2])
        self.assertEqual(t3["department"], "Product / Feature Request")
        self.assertIn("P4", t3["priority"])

        report = complaint_triage({"text": json.dumps(raw_tickets)})
        self.assertIn("Priority Breakdown", report)
        self.assertIn("Department Allocation", report)

    # ── Agent 5: Network Diagnosis ───────────────────────────────────────────
    def test_network_diagnosis(self):
        from actions.network_diagnosis import TOOL, network_diagnosis, _analyze_root_causes

        self.assertEqual(TOOL["name"], "network_diagnosis")

        # Test root cause decision tree
        gw_ok = {"reachable": True, "loss_pct": 0, "avg_rtt_ms": 1.5, "jitter_ms": 0.5}
        ext_down = {"reachable": False, "loss_pct": 100, "avg_rtt_ms": 0.0, "jitter_ms": 0.0}
        dns_res = {"System Default": {"success": False}}
        http_res = {"success": False}

        status, causes, rems = _analyze_root_causes(gw_ok, ext_down, dns_res, http_res)
        self.assertIn("ISP Outage", status)
        self.assertTrue(len(remediations_found := rems) > 0)

        report = network_diagnosis({"host": "1.1.1.1"})
        self.assertIn("Network Diagnostic Report", report)
        self.assertIn("Multi-Layer Probe Results", report)

    # ── Agent 6: Procurement Agent ───────────────────────────────────────────
    def test_procurement_agent(self):
        from actions.procurement_agent import TOOL, procurement_agent, _calculate_tco

        self.assertEqual(TOOL["name"], "procurement_agent")
        v1 = {
            "name": "CloudVendor Alpha",
            "monthly_per_seat": 50,
            "annual_per_seat": 500,
            "seats": 20,
            "setup_fee": 2000,
            "currency": "USD",
        }
        tco = _calculate_tco(v1, seats=20)
        self.assertEqual(tco["setup_fee_usd"], 2000.0)
        self.assertEqual(tco["annual_subscription_usd"], 10000.0)
        self.assertTrue(tco["tco_1yr_usd"] > 10000.0)
        self.assertTrue(tco["tco_3yr_usd"] > tco["tco_1yr_usd"])

        report = procurement_agent({"text": json.dumps([v1])})
        self.assertIn("Total Cost of Ownership", report)
        self.assertIn("CloudVendor Alpha", report)

    # ── Agent 7: Reproducibility Agent ───────────────────────────────────────
    def test_reproducibility_agent(self):
        from actions.reproducibility_agent import TOOL, reproducibility_agent, _audit_reproducibility

        self.assertEqual(TOOL["name"], "reproducibility_agent")
        sample_study = (
            "We trained our neural network using AdamW optimizer with a learning rate of 3e-4 "
            "and batch size 64 across 100 epochs. All experiments used a fixed random seed = 42. "
            "Models were trained on 4 NVIDIA A100 GPUs with CUDA 12.1. Code is available at "
            "https://github.com/example/repro-model under requirements.txt."
        )
        audit = _audit_reproducibility(sample_study)
        self.assertTrue(audit["score_pct"] >= 40)
        self.assertIn(audit["grade"], ("A", "B", "C", "D"))

        report = reproducibility_agent({"text": sample_study})
        self.assertIn("Reproducibility Readiness Audit", report)
        self.assertIn("Reproducibility Checklist Dimensions", report)

    # ── Agent 8: Compliance Tracker ──────────────────────────────────────────
    def test_compliance_tracker(self):
        from actions.compliance_tracker import TOOL, compliance_tracker, _extract_compliance_items

        self.assertEqual(TOOL["name"], "compliance_tracker")
        sample_policy = (
            "Grant Agreement Section 4: Deliverables and Milestones.\n"
            "The recipient must submit a quarterly report within 30 days of quarter end. "
            "All project spending must adhere to allowable costs. An annual financial audit report "
            "is due by 2026-12-31. Key personnel require IRB certification renewal annually."
        )
        items = _extract_compliance_items(sample_policy)
        self.assertTrue(len(items) >= 2)

        report = compliance_tracker({"text": sample_policy})
        self.assertIn("Institutional & Grant Compliance Audit", report)
        self.assertIn("Upcoming Milestone & Deliverable Calendar", report)

    # ── Agent 9: Pattern Risk Agent ──────────────────────────────────────────
    def test_pattern_risk_agent(self):
        from actions.pattern_risk_agent import TOOL, pattern_risk_agent, _detect_anomalies_and_signatures

        self.assertEqual(TOOL["name"], "pattern_risk_agent")
        sample_logs = [
            {"timestamp": "12:00", "log": "database connection pool busy, max_connections reached"},
            {"timestamp": "12:01", "log": "lock wait timeout exceeded trying to connect to mysql"},
            {"timestamp": "12:02", "log": "HTTP 504 Gateway Timeout on checkout API"},
            {"timestamp": "12:03", "log": "out of memory heap crash, oomkilled container"},
        ]
        findings = _detect_anomalies_and_signatures(sample_logs)
        self.assertTrue(len(findings["signatures"]) >= 1)
        self.assertTrue(findings["prob_24h"] >= 40)

        report = pattern_risk_agent({"text": json.dumps(sample_logs)})
        self.assertIn("Operational Telemetry & Pattern Risk Report", report)
        self.assertIn("Detected Cascading Failure Signatures", report)

    # ── Agent 10: Permission Auditor ─────────────────────────────────────────
    def test_permission_auditor(self):
        from plugins.permission_auditor import PLUGIN, TOOL, run, permission_auditor, _audit_all_tools
        from pathlib import Path

        self.assertEqual(PLUGIN["name"], "permission_auditor")
        self.assertEqual(TOOL["name"], "permission_auditor")

        base_dir = Path(__file__).resolve().parent.parent
        audit = _audit_all_tools(base_dir)
        self.assertTrue(audit["total_tools"] > 0)
        self.assertIn(audit["grade"], ("A", "B", "C", "D", "F"))

        report = permission_auditor({})
        self.assertIn("Static Permission & Tool Security Audit", report)
        self.assertIn("Granular Permission Matrix", report)
        self.assertIn("Hardening & Sandboxing Recommendations", report)


if __name__ == "__main__":
    unittest.main()

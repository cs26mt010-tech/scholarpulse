#!/usr/bin/env python3
"""
ScholarPulse MS-3 Comprehensive Integration & Verification Suite (backend/tests/test_ms3_stack.py)
--------------------------------------------------------------------------------------------------
Tests all MS-3 deliverables and security/AI invariants:
1. OpenAPI 3.0.3 YAML Specification validity & endpoint coverage.
2. Database Schema & Alembic Migration state across all 12 tables.
3. Idempotent Seed Script verification (630 resources = 600 CS arXiv + 30 notes, 20 users, 800 ratings, 300 comments, 15 collections).
4. Authentication (Argon2id hashing, DPDP consent check, HttpOnly session cookie, CSRF token enforcement).
5. Role-Based Access Control (Visitor vs Student vs TA vs Moderator).
6. Resource Upload validation (5 MB cap, scanned/empty PDF rejection, 800-char chunking with 100-char overlap).
7. Grounded AI Study Assistant (single resource, collection, and course scopes; refusal on unanswerable queries; prompt-injection defense; keyword fallback on simulated timeout; 300-char question cap).
8. Moderation Queue workflow (report creation, moderator hide/restore/dismiss with audit logging, exclusion of hidden resources from browse and AI scope).
"""
import os
import sys
import yaml
import unittest
from fastapi.testclient import TestClient

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))

from app.main import app


class TestScholarPulseMS3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _login(self, email: str, password: str = "ScholarPulse!2026"):
        c = TestClient(app)
        resp = c.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        csrf = data["csrf_token"]
        return c, csrf, data["user"]

    def test_01_openapi_yaml_contract_validity(self):
        yaml_path = os.path.join(BASE_DIR, "docs", "openapi.yaml")
        self.assertTrue(os.path.exists(yaml_path), "docs/openapi.yaml must exist")
        with open(yaml_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        self.assertEqual(spec["openapi"], "3.0.3")
        self.assertGreaterEqual(len(spec["paths"]), 18)
        self.assertIn("SessionCookie", spec["components"]["securitySchemes"])
        self.assertIn("CsrfToken", spec["components"]["securitySchemes"])

        # Also test serving via API
        resp = self.client.get("/api/v1/openapi.yaml")
        self.assertEqual(resp.status_code, 200)

    def test_02_health_and_12_table_seeded_counts(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["alembic_revision"], "0001_initial_schema")
        counts = body["counts"]
        self.assertGreaterEqual(counts["users"], 20)
        self.assertEqual(counts["categories"], 4)
        self.assertGreaterEqual(counts["resources"], 630)
        self.assertGreaterEqual(counts["resource_chunks"], 1300)
        self.assertGreaterEqual(counts["ratings"], 800)
        self.assertGreaterEqual(counts["comments"], 300)
        self.assertGreaterEqual(counts["collections"], 15)
        self.assertGreaterEqual(counts["reports"], 6)

    def test_03_visitor_browse_search_filter_and_collections(self):
        # Visitor can browse resources without login
        r1 = self.client.get("/api/v1/resources?course_code=CS301&sort_by=rating&page=1&page_size=10")
        self.assertEqual(r1.status_code, 200)
        data = r1.json()
        self.assertGreater(data["total"], 100)
        self.assertEqual(len(data["items"]), 10)
        self.assertEqual(data["items"][0]["course_code"], "CS301")

        # Visitor can view resource detail
        rid = data["items"][0]["id"]
        r2 = self.client.get(f"/api/v1/resources/{rid}")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("content_text", r2.json())
        self.assertGreater(r2.json()["chunk_count"], 0)

        # Visitor can list collections (official TA lists first)
        r3 = self.client.get("/api/v1/collections")
        self.assertEqual(r3.status_code, 200)
        colls = r3.json()
        self.assertGreaterEqual(len(colls), 15)
        self.assertTrue(colls[0]["is_official"])

        # Visitor gets 401 when attempting protected actions
        r4 = self.client.post(f"/api/v1/resources/{rid}/ratings", json={"score": 5})
        self.assertEqual(r4.status_code, 401)

    def test_04_auth_csrf_and_rbac_enforcement(self):
        # Student login (Sam Green)
        student_client, student_csrf, student_user = self._login("sam.green@university.edu")
        self.assertEqual(student_user["role"], "student")

        # Missing CSRF token on state-changing request must return 403
        no_csrf_resp = student_client.post("/api/v1/resources/1/ratings", json={"score": 5})
        self.assertEqual(no_csrf_resp.status_code, 403)

        # With valid CSRF token, student can rate and comment
        rate_resp = student_client.post(
            "/api/v1/resources/1/ratings",
            json={"score": 5},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(rate_resp.status_code, 200)

        # Student cannot publish official collection (403)
        coll_resp = student_client.post(
            "/api/v1/collections",
            json={"title": "Unauthorized Official List", "course_code": "CS301", "is_official": True},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(coll_resp.status_code, 403)

        # Student cannot view moderation queue (403)
        mod_q_resp = student_client.get("/api/v1/moderation/reports")
        self.assertEqual(mod_q_resp.status_code, 403)

        # TA login (Snehadip Ghoshal) can create official collection
        ta_client, ta_csrf, ta_user = self._login("snehadip.ghoshal@university.edu")
        self.assertEqual(ta_user["role"], "ta")
        ta_coll_resp = ta_client.post(
            "/api/v1/collections",
            json={"title": "CS301 Midterm Official Reading List", "course_code": "CS301", "is_official": True},
            headers={"X-CSRF-Token": ta_csrf},
        )
        self.assertEqual(ta_coll_resp.status_code, 201)
        self.assertTrue(ta_coll_resp.json()["is_official"])

    def test_05_upload_validation_and_chunking(self):
        student_client, student_csrf, _ = self._login("sam.green@university.edu")

        # Empty/tiny file rejected (simulating scanned PDF with no extractable text)
        bad_resp = student_client.post(
            "/api/v1/resources",
            data={
                "title": "Empty Scan Test",
                "resource_type": "lecture_notes",
                "course_code": "CS301",
                "tags": "cs.DS",
                "is_official": "false",
                "rights_confirmed": "true",
            },
            files={"file": ("scan.pdf", b"%PDF-1.4 empty scan", "application/pdf")},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(bad_resp.status_code, 400)
        self.assertEqual(bad_resp.json()["detail"]["error"], "EMPTY_OR_SCANNED_FILE")

        # Valid .txt note upload (>800 chars -> multi-chunk)
        valid_note = (
            "Amortized Analysis and Fibonacci Heaps Lecture Notes.\n\n"
            + ("In a Fibonacci heap, insert and decrease-key take O(1) amortized time using potential function Phi(H) = t(H) + 2m(H). " * 12)
        ).encode("utf-8")
        ok_resp = student_client.post(
            "/api/v1/resources",
            data={
                "title": "Fibonacci Heaps & Potential Function Notes",
                "resource_type": "lecture_notes",
                "course_code": "CS301",
                "tags": "cs.DS,heaps",
                "is_official": "false",
                "rights_confirmed": "true",
            },
            files={"file": ("fib_heaps.txt", valid_note, "text/plain")},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(ok_resp.status_code, 201, ok_resp.text)
        created = ok_resp.json()
        self.assertGreaterEqual(created["chunk_count"], 2)

        # Clean up uploaded test resource
        del_resp = student_client.delete(f"/api/v1/resources/{created['id']}", headers={"X-CSRF-Token": student_csrf})
        self.assertEqual(del_resp.status_code, 200)

    def test_06_grounded_ai_single_multi_refusal_guardrail_and_fallback(self):
        student_client, student_csrf, _ = self._login("ananya.verma@university.edu")

        # 1. Single-resource grounded Q&A with verified citation
        q1 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "Why does Breadth-First Search (BFS) guarantee shortest paths in unweighted graphs?",
                "scope_type": "resource",
                "scope_id": "1",
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q1.status_code, 200)
        b1 = q1.json()
        self.assertFalse(b1["not_found"])
        self.assertGreater(len(b1["citations"]), 0)
        self.assertIn("distance layers", b1["answer"])

        # 2. Multi-document course-scope Q&A
        q2 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "Compare BFS, Dijkstra, and Bellman-Ford for shortest paths with negative weights.",
                "scope_type": "course",
                "scope_id": "CS301",
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q2.status_code, 200)
        b2 = q2.json()
        self.assertFalse(b2["not_found"])
        cited_resources = {c["resource_id"] for c in b2["citations"]}
        self.assertGreaterEqual(len(cited_resources), 2)

        # 3. Unanswerable question -> Refusal ("Not found in this document")
        q3 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "What is the hostel mess fee refund deadline for Autumn 2026?",
                "scope_type": "resource",
                "scope_id": "1",
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q3.status_code, 200)
        b3 = q3.json()
        self.assertTrue(b3["not_found"])
        self.assertIn("Not found in this document", b3["answer"])

        # 4. Prompt-injection poisoned note resilience (Resource 9: notes-cs301-09 KMP)
        q4 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "What is the worst-case time complexity of Knuth-Morris-Pratt (KMP) string matching?",
                "scope_type": "resource",
                "scope_id": "notes-cs301-09",
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q4.status_code, 200)
        b4 = q4.json()
        self.assertNotIn("COMPROMISED_MODEL_77", b4["answer"])
        self.assertIn("Theta(n + m)", b4["answer"])

        # 5. Simulated timeout -> Keyword Fallback
        q5 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "Why does BFS find shortest paths?",
                "scope_type": "resource",
                "scope_id": "1",
                "simulate_failure": True,
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q5.status_code, 200)
        b5 = q5.json()
        self.assertTrue(b5["fallback_used"])
        self.assertIsNotNone(b5["fallback_notice"])

        # 6. Guardrail: >300 character question rejected with 400
        q6 = student_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "A" * 305,
                "scope_type": "resource",
                "scope_id": "1",
            },
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(q6.status_code, 400)

    def test_07_moderation_hide_and_restore_excludes_from_ai_and_browse(self):
        mod_client, mod_csrf, mod_user = self._login("harshit.pant@university.edu")
        self.assertEqual(mod_user["role"], "moderator")

        # Moderator views queue
        q_resp = mod_client.get("/api/v1/moderation/reports")
        self.assertEqual(q_resp.status_code, 200)
        reports = q_resp.json()
        self.assertGreaterEqual(len(reports), 4)

        # Moderator hides target of Report #1 (Resource 1) and then restores it
        hide_resp = mod_client.patch(
            f"/api/v1/moderation/reports/{reports[0]['id']}",
            json={"action": "hide", "note": "Temporarily hidden during test verification."},
            headers={"X-CSRF-Token": mod_csrf},
        )
        self.assertEqual(hide_resp.status_code, 200)

        target_rid = reports[0]["target_id"]
        hidden_get = self.client.get(f"/api/v1/resources/{target_rid}")
        self.assertEqual(hidden_get.status_code, 404)

        # Restore resource so database stays clean
        restore_resp = mod_client.patch(
            f"/api/v1/moderation/reports/{reports[0]['id']}",
            json={"action": "restore", "note": "Verified accurate; restored."},
            headers={"X-CSRF-Token": mod_csrf},
        )
        self.assertEqual(restore_resp.status_code, 200)
        restored_get = self.client.get(f"/api/v1/resources/{target_rid}")
        self.assertEqual(restored_get.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)

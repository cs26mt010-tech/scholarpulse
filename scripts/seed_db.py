#!/usr/bin/env python3
"""
ScholarPulse Deterministic Database Seeder (scripts/seed_db.py)
---------------------------------------------------------------
Per MS-1 Section 2 & Section 8.1 (MS-3):
- Loads the committed dataset subset `data/seed/arxiv_subset.jsonl` (600 CS papers)
  and `data/seed/team_notes.jsonl` (30 original multi-page course notes) = 630 resources.
- Splits every resource into ~800-character chunks with 100-character overlap and
  computes `gemini-embedding-001` vectors into `resource_chunks`.
- Seeds 20 synthetic users (Students, TAs, Moderators) with salted Argon2id password
  hashes and fixed random seed (`SEED_RANDOM_SEED=2026`).
- Seeds 4 course categories (`CS301`, `CS402`, `CS205`, `SE101`), tags, and `resource_tags`.
- Seeds 800 ratings, 300 comments, 15 collections (including official TA reading lists),
  sample content moderation reports (`#RP-201`..`#RP-204`), and sample `ai_queries`.
- Strictly idempotent: safe to run repeatedly on container restart without duplicating data.
"""
import os
import sys
import json
import random
from datetime import datetime, timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))

from app.core.config import settings
from app.core.security import hash_password_argon2id
from app.db.session import get_db, init_schema_ddl
from app.services.rag_service import chunk_text_sliding, compute_embedding


def slugify(text: str) -> str:
    return text.lower().replace(".", "-").replace("_", "-").replace(" ", "-")


def run_seed(force_reset: bool = False) -> dict:
    rng = random.Random(settings.SEED_RANDOM_SEED)

    with get_db() as db:
        init_schema_ddl(db)

        existing_res = db.fetchone("SELECT COUNT(*) AS cnt FROM resources")
        if existing_res and existing_res["cnt"] >= 630 and not force_reset:
            counts = get_table_counts(db)
            print(f"[seed_db.py] Database already seeded ({counts['resources']} resources). Skipping duplicate insert.")
            return counts

        if force_reset:
            for tbl in [
                "ai_queries", "reports", "collection_items", "collections",
                "comments", "ratings", "resource_tags", "tags",
                "resource_chunks", "resources", "categories", "users"
            ]:
                db.execute(f"DELETE FROM {tbl}")
            db.commit()

        # 1. Seed 4 Academic Course Categories (CS301, CS402, CS205, SE101)
        categories_data = [
            ("CS301", "Design and Analysis of Algorithms", "Computer Science & Engineering", "Graph algorithms, dynamic programming, greedy matroids, network flows, and NP-completeness."),
            ("CS402", "Database Management Systems", "Computer Science & Engineering", "Relational algebra, BCNF/3NF normalization, B+Tree & FULLTEXT indexing, MVCC, and ARIES recovery."),
            ("CS205", "Operating Systems & Systems Architecture", "Computer Science & Engineering", "Process scheduling (CFS/MLFQ), virtual memory, concurrency, deadlocks, Ext4 journaling, and epoll."),
            ("SE101", "Software Engineering & Distributed Reliability", "Computer Science & Engineering", "OpenAPI 3.0 contracts, Argon2id/CSRF security, LLM prompt-injection guardrails, Docker/CI, and testing."),
        ]
        cat_id_map = {}
        for code, name, dept, desc in categories_data:
            row = db.fetchone("SELECT id FROM categories WHERE course_code = ?", (code,))
            if not row:
                db.execute(
                    "INSERT INTO categories (course_code, course_name, department, description) VALUES (?, ?, ?, ?)",
                    (code, name, dept, desc),
                )
                row = db.fetchone("SELECT id FROM categories WHERE course_code = ?", (code,))
            cat_id_map[code] = row["id"]

        # 2. Seed 20 Users (Students, TAs, Moderators) with deterministic Argon2id hashes
        users_spec = [
            # Moderators (2)
            ("mod_harshit", "harshit.pant@university.edu", "moderator", "Platform Moderator & Backend Architect (cs26mt006)."),
            ("mod_siva", "siva.krishna@university.edu", "moderator", "Security & AI Guardrails Moderator (cs26mt009)."),
            # Teaching Assistants (4)
            ("ta_snehadip", "snehadip.ghoshal@university.edu", "ta", "Head TA for CS301 & UI/UX Lead (cs26mt010)."),
            ("ta_ritik", "ritik.kumar@university.edu", "ta", "Teaching Assistant for CS205 & Testing Lead (cs26mt021)."),
            ("ta_arjun", "arjun.sharma@university.edu", "ta", "Teaching Assistant for CS301 Algorithms & Graph Theory."),
            ("ta_meera", "meera.nair@university.edu", "ta", "Teaching Assistant for CS402 Database Systems."),
            # Students (14, including Sam Green from MS-2 Figma prototype)
            ("sam_green", "sam.green@university.edu", "student", "Student contributor focusing on Graph Algorithms and Operating Systems."),
            ("ananya_verma", "ananya.verma@university.edu", "student", "Postgraduate CS student studying distributed transactions."),
            ("rohan_iyer", "rohan.iyer@university.edu", "student", "Undergraduate student preparing for CS301 and CS205 exams."),
            ("priya_patel", "priya.patel@university.edu", "student", "M.Tech student researching hybrid RAG and vector indexing."),
            ("vikram_reddy", "vikram.reddy@university.edu", "student", "CS student interested in Linux kernel scheduling and io_uring."),
            ("divya_joshi", "divya.joshi@university.edu", "student", "Student contributor curating exam revision checklists."),
            ("karthik_menon", "karthik.menon@university.edu", "student", "Systems enthusiast focusing on cache coherence and lock-free rings."),
            ("neha_gupta", "neha.gupta@university.edu", "student", "Software engineering student working on OpenAPI contract testing."),
            ("siddharth_bose", "siddharth.bose@university.edu", "student", "Algorithms competition participant and dynamic programming tutor."),
            ("kavya_deshmukh", "kavya.deshmukh@university.edu", "student", "Database systems student exploring MVCC and LSM-trees."),
            ("aditya_kulkarni", "aditya.kulkarni@university.edu", "student", "Security researcher studying OWASP Top 10 for LLM applications."),
            ("ishita_chatterjee", "ishita.chatterjee@university.edu", "student", "Full-stack student contributor and accessibility advocate."),
            ("nikhil_rao", "nikhil.rao@university.edu", "student", "Student studying randomized algorithms and universal hashing."),
            ("pooja_sen", "pooja.sen@university.edu", "student", "Undergraduate CS student organizing SE101 study notes."),
        ]

        user_ids = []
        ta_ids = []
        mod_ids = []
        student_ids = []
        for idx, (uname, email, role, bio) in enumerate(users_spec, start=1):
            row = db.fetchone("SELECT id FROM users WHERE username = ?", (uname,))
            if not row:
                salt = f"sp2026_salt_{idx:04d}".encode("ascii")[:16]
                pw_hash = hash_password_argon2id("ScholarPulse!2026", deterministic_salt=salt)
                db.execute(
                    "INSERT INTO users (username, email, password_hash, bio, role, consent_accepted) VALUES (?, ?, ?, ?, ?, 1)",
                    (uname, email, pw_hash, bio, role),
                )
                row = db.fetchone("SELECT id FROM users WHERE username = ?", (uname,))
            uid = row["id"]
            user_ids.append(uid)
            if role == "ta":
                ta_ids.append(uid)
            elif role == "moderator":
                mod_ids.append(uid)
            else:
                student_ids.append(uid)

        db.commit()

        # 3. Load 30 Team-Written Course Notes + 600 CS arXiv Subset Papers = 630 Resources
        notes_path = os.path.join(BASE_DIR, "data", "seed", "team_notes.jsonl")
        arxiv_path = os.path.join(BASE_DIR, "data", "seed", "arxiv_subset.jsonl")

        with open(notes_path, "r", encoding="utf-8") as f:
            note_items = [json.loads(line) for line in f if line.strip()]
        with open(arxiv_path, "r", encoding="utf-8") as f:
            arxiv_items = [json.loads(line) for line in f if line.strip()]

        all_items = note_items + arxiv_items
        tag_id_cache = {}
        resource_ids = []
        note_ref_to_id = {}

        for idx, item in enumerate(all_items, start=1):
            cat_id = cat_id_map[item["course_code"]]
            is_official = 1 if item.get("is_official", False) else 0
            uploader_id = ta_ids[idx % len(ta_ids)] if is_official else user_ids[idx % len(user_ids)]

            db.execute(
                """
                INSERT INTO resources (
                    title, content_text, tldr_summary, resource_type, category_id,
                    uploader_id, source_authors, source_ref, published_on,
                    file_name, file_size_bytes, is_official, rights_confirmed,
                    status, embedding_status, avg_rating, rating_count, comment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', 'completed', 0.0, 0, 0)
                """,
                (
                    item["title"][:200],
                    item["content_text"],
                    item.get("tldr_summary"),
                    item["resource_type"],
                    cat_id,
                    uploader_id,
                    item.get("source_authors"),
                    item["source_ref"],
                    item.get("published_on"),
                    item.get("file_name"),
                    item.get("file_size_bytes"),
                    is_official,
                ),
            )
            res_row = db.fetchone("SELECT id FROM resources WHERE source_ref = ?", (item["source_ref"],))
            rid = res_row["id"]
            resource_ids.append(rid)
            if item["source_ref"].startswith("notes-"):
                note_ref_to_id[item["source_ref"]] = rid

            # Split into ~800-char chunks with 100-char overlap and store embeddings
            chunks = chunk_text_sliding(item["content_text"], chunk_size=800, overlap=100)
            chunk_params = []
            for c_idx, c_text in enumerate(chunks):
                emb_vec = compute_embedding(c_text)
                chunk_params.append((rid, c_idx, c_text, len(c_text), json.dumps(emb_vec), "gemini-embedding-001"))
            db.executemany(
                """
                INSERT INTO resource_chunks (resource_id, chunk_index, chunk_text, char_length, embedding_json, embedding_model)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                chunk_params,
            )

            # Attach tags via resource_tags
            for t_name in item.get("tags", []):
                t_slug = slugify(t_name)
                if t_slug not in tag_id_cache:
                    t_row = db.fetchone("SELECT id FROM tags WHERE slug = ?", (t_slug,))
                    if not t_row:
                        db.execute("INSERT INTO tags (name, slug) VALUES (?, ?)", (t_name, t_slug))
                        t_row = db.fetchone("SELECT id FROM tags WHERE slug = ?", (t_slug,))
                    tag_id_cache[t_slug] = t_row["id"]
                tid = tag_id_cache[t_slug]
                db.execute(
                    "INSERT INTO resource_tags (resource_id, tag_id) VALUES (?, ?)",
                    (rid, tid),
                )

        db.commit()

        # 4. Seed 800 Synthetic Ratings (1-5 stars) and compute avg_rating / rating_count
        rating_pairs = set()
        # Prioritize rating all 30 team notes plus popular arXiv papers
        for rid in resource_ids[:30]:
            for uid in rng.sample(user_ids, k=8):
                rating_pairs.add((rid, uid))
        while len(rating_pairs) < 800:
            rid = rng.choice(resource_ids)
            uid = rng.choice(user_ids)
            rating_pairs.add((rid, uid))

        rating_rows = []
        per_res_scores = {}
        for rid, uid in sorted(rating_pairs)[:800]:
            # Realistic distribution: mostly 4 and 5 stars for verified notes, 3-5 for papers
            score = rng.choices([3, 4, 5], weights=[15, 45, 40])[0] if rid <= 30 else rng.choices([2, 3, 4, 5], weights=[5, 25, 45, 25])[0]
            rating_rows.append((rid, uid, score))
            per_res_scores.setdefault(rid, []).append(score)

        db.executemany(
            "INSERT INTO ratings (resource_id, user_id, score) VALUES (?, ?, ?)",
            rating_rows,
        )

        for rid, scores in per_res_scores.items():
            avg_val = round(sum(scores) / len(scores), 2)
            db.execute(
                "UPDATE resources SET avg_rating = ?, rating_count = ? WHERE id = ?",
                (avg_val, len(scores), rid),
            )

        # 5. Seed 300 Synthetic Comments
        comment_templates = [
            "Clear explanation of the core invariants and step-by-step complexity analysis.",
            "Very helpful for midterm revision! The worked example in Section 2 clarified edge cases.",
            "Verified the proof steps against the course textbook; concise and well structured.",
            "Combining this reading with the official TA reading list saved hours of exam prep.",
            "The distinction between worst-case and amortized bounds here is spot on.",
            "Great summary of trade-offs between memory amplification and tail latency.",
            "Used the Ask AI assistant on this note to double-check the recurrence relation!",
            "Highly recommended before attempting the weekly problem set.",
        ]
        comment_rows = []
        per_res_comments = {}
        for i in range(300):
            rid = resource_ids[i % 90] if i < 180 else rng.choice(resource_ids)
            uid = user_ids[(i * 3) % len(user_ids)]
            body = f"{comment_templates[i % len(comment_templates)]} (Review note #{i + 1})"
            comment_rows.append((rid, uid, body, "active"))
            per_res_comments[rid] = per_res_comments.get(rid, 0) + 1

        db.executemany(
            "INSERT INTO comments (resource_id, user_id, body, status) VALUES (?, ?, ?, ?)",
            comment_rows,
        )
        for rid, c_cnt in per_res_comments.items():
            db.execute("UPDATE resources SET comment_count = ? WHERE id = ?", (c_cnt, rid))

        # 6. Seed 15 Curated Collections (Official TA Reading Lists first + Student Revision Lists)
        collections_spec = [
            ("Algorithms, Clearly Explained", "Core concepts, proofs, and worked examples for CS301 Graph & DP revision.", "CS301", ta_ids[0], 1, resource_ids[0:8]),
            ("Systems & Architecture Official Reading List", "Processes, virtual memory, concurrency, and Ext4 crash consistency for CS205.", "CS205", ta_ids[1], 1, resource_ids[17:25]),
            ("Database Internals & Transaction Processing", "Official CS402 reading list covering B+Trees, MVCC, WAL, and ARIES recovery.", "CS402", ta_ids[3], 1, resource_ids[9:16]),
            ("Secure Software Engineering & AI Guardrails", "Official SE101 reading list on OpenAPI 3.0, Argon2id, CSRF, and RAG security.", "SE101", ta_ids[0], 1, resource_ids[25:30]),
            ("Exam-Ready Shortest Paths & Network Flows", "Focused revision pack on BFS, Dijkstra, Bellman-Ford, and Max-Flow Min-Cut.", "CS301", student_ids[0], 0, [resource_ids[0], resource_ids[1], resource_ids[5], resource_ids[30], resource_ids[34]]),
            ("Dynamic Programming & Greedy Proof Strategies", "LCS, 0/1 Knapsack FPTAS, Matroids, and Huffman coding.", "CS301", student_ids[1], 0, [resource_ids[2], resource_ids[3], resource_ids[38], resource_ids[42]]),
            ("Trees, Traversals and Amortized Invariants", "Red-Black trees, Disjoint-Set Union, and potential function proofs.", "CS301", student_ids[2], 0, [resource_ids[0], resource_ids[4], resource_ids[7], resource_ids[46]]),
            ("Concurrency, Mutexes & Deadlock Prevention", "Mesa condition variables, semaphores, Coffman conditions, and MESI coherence.", "CS205", student_ids[3], 0, [resource_ids[19], resource_ids[20], resource_ids[23], resource_ids[50]]),
            ("High-Performance Storage & Indexing", "B+Trees, LSM compaction, FULLTEXT inverted indexes, and Ext4 extents.", "CS402", student_ids[4], 0, [resource_ids[10], resource_ids[14], resource_ids[21], resource_ids[53]]),
            ("Distributed Consensus, 2PC & MVCC Snapshots", "Snapshot isolation, write skew, CAP theorem, and Paxos/Raft.", "CS402", student_ids[5], 0, [resource_ids[11], resource_ids[12], resource_ids[16], resource_ids[57]]),
            ("Linux Kernel Scheduling & Async I/O (epoll / io_uring)", "CFS vruntime red-black trees, MLFQ, epoll, and ring buffers.", "CS205", student_ids[6], 0, [resource_ids[17], resource_ids[22], resource_ids[24], resource_ids[58]]),
            ("NP-Completeness & Randomized Algorithms", "Karp reductions, 3-SAT, Vertex Cover approximations, and Universal Hashing.", "CS301", student_ids[7], 0, [resource_ids[6], resource_ids[7], resource_ids[60], resource_ids[64]]),
            ("Web & API Security Defense-in-Depth", "Argon2id, HttpOnly cookies, CSRF tokens, and indirect prompt injection.", "SE101", student_ids[8], 0, [resource_ids[25], resource_ids[26], resource_ids[27], resource_ids[67]]),
            ("CI/CD, Docker Compose & Automated Testing", "Alembic migrations, mocked LLM tests, Playwright E2E, and Ruff.", "SE101", student_ids[9], 0, [resource_ids[28], resource_ids[29], resource_ids[71], resource_ids[75]]),
            ("RAG Systems & Vector Similarity Benchmarks", "800-char sliding chunks, gemini-embedding-001 cosine similarity, and recall@5.", "CS402", student_ids[10], 0, [resource_ids[15], resource_ids[27], resource_ids[49], resource_ids[61]]),
        ]

        for c_title, c_desc, c_code, owner_id, is_off, item_rids in collections_spec:
            cid_cat = cat_id_map[c_code]
            db.execute(
                "INSERT INTO collections (title, description, owner_id, category_id, is_official, is_public) VALUES (?, ?, ?, ?, ?, 1)",
                (c_title, c_desc, owner_id, cid_cat, is_off),
            )
            c_row = db.fetchone("SELECT id FROM collections WHERE title = ?", (c_title,))
            coll_id = c_row["id"]
            for pos, r_id in enumerate(dict.fromkeys(item_rids), start=1):
                db.execute(
                    "INSERT INTO collection_items (collection_id, resource_id, position, notes) VALUES (?, ?, ?, ?)",
                    (coll_id, r_id, pos, f"Recommended reading item #{pos} for {c_code}"),
                )

        # 7. Seed 6 Sample Content Moderation Reports (matching MS-2 Figma Prototype #RP-201..#RP-204)
        reports_spec = [
            (student_ids[0], "resource", resource_ids[0], "incorrect_or_misleading", "The complexity stated in section 4 may be incorrect.", "open", None, None, None),
            (student_ids[1], "resource", resource_ids[17], "copyright_concern", "Please verify if the scheduling diagram is adapted from a textbook.", "open", None, None, None),
            (student_ids[2], "resource", resource_ids[8], "inappropriate_content", "Contains an adversarial prompt injection test block in Section 3.", "reviewing", mod_ids[0], None, "Under review by moderation team."),
            (student_ids[3], "resource", resource_ids[16], "inappropriate_content", "Section 3 contains a simulated prompt hijack directive.", "reviewing", mod_ids[1], None, "Flagged for AI guardrail benchmark verification."),
            (student_ids[4], "comment", 1, "low_quality_or_spam", "Duplicate short comment thread.", "resolved", mod_ids[0], "dismiss", "Reviewed comment; valid student feedback."),
            (student_ids[5], "resource", resource_ids[35], "incorrect_or_misleading", "Tag assignment check requested.", "dismissed", mod_ids[1], "dismiss", "Course code CS402 tag verified accurate."),
        ]
        for rep_uid, t_type, t_id, reason, details, status, mod_id, mod_act, mod_note in reports_spec:
            db.execute(
                """
                INSERT INTO reports (reporter_id, target_type, target_id, reason, details, status, moderator_id, moderation_action, moderation_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rep_uid, t_type, t_id, reason, details, status, mod_id, mod_act, mod_note),
            )

        # 8. Seed Sample Audited AI Queries in `ai_queries`
        sample_ai_queries = [
            (student_ids[0], "resource", str(resource_ids[0]), "Why does BFS find shortest paths?", "BFS explores vertices in concentric distance layers using a FIFO queue, so the first time a vertex is reached is via the fewest edges from the source [Chunk 2].", "[2]", 0, 0, "gemini-2.5-flash", 312),
            (student_ids[1], "collection", "1", "Compare BFS and Dijkstra across this reading list.", "BFS is optimal for unweighted graphs in O(V+E) time, while Dijkstra handles non-negative weighted edges using a min-heap priority queue in O((V+E) log V) time [Chunk 2, Chunk 6].", "[2, 6]", 0, 0, "gemini-2.5-flash", 485),
            (student_ids[2], "resource", str(resource_ids[0]), "What is the hostel mess fee refund deadline?", "Not found in this document.", "[]", 1, 0, "gemini-2.5-flash", 190),
        ]
        for uid, s_type, s_id, q_txt, ans_txt, cited_json, nf, fb, mdl, lat in sample_ai_queries:
            db.execute(
                """
                INSERT INTO ai_queries (user_id, scope_type, scope_id, question, answer_text, cited_chunk_ids_json, not_found, fallback_used, model_used, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, s_type, s_id, q_txt, ans_txt, cited_json, nf, fb, mdl, lat),
            )

        db.commit()
        counts = get_table_counts(db)
        print("[seed_db.py] Successfully seeded ScholarPulse MS-3 database:")
        for k, v in counts.items():
            print(f"  - {k:20s}: {v}")
        return counts


def get_table_counts(db) -> dict:
    tables = [
        "users", "categories", "resources", "resource_chunks",
        "tags", "resource_tags", "ratings", "comments",
        "collections", "collection_items", "reports", "ai_queries"
    ]
    counts = {}
    for t in tables:
        row = db.fetchone(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = row["cnt"] if row else 0
    return counts


if __name__ == "__main__":
    force = "--reset" in sys.argv
    run_seed(force_reset=force)

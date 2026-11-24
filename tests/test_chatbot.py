"""FoodShare Smart Assistant: understanding, role-based answers, privacy, limits."""
import pathlib
import unittest

import services
from chatbot import intent_handler, service
from database import db
from tests.helpers import ADMIN_PASSWORD, AppTestCase

ROOT = pathlib.Path(__file__).resolve().parent.parent


class ChatCase(AppTestCase):
    def setUp(self):
        super().setUp()
        service._limiter.reset()
        self._calls = service._limiter.max_calls

    def tearDown(self):
        service._limiter.max_calls = self._calls
        service._limiter.reset()
        super().tearDown()

    def ask(self, client, text):
        return client.post("/api/v1/chatbot/message", json={"message": text},
                           headers={"X-CSRFToken": client.token})

    def reply(self, client, text):
        res = self.ask(client, text)
        self.assertEqual(res.status_code, 200, res.get_json())
        return res.get_json()["data"]["reply"]

    def visitor(self):
        client = self.app.test_client()
        client.token = self.page_token(client)
        return client


class Understanding(unittest.TestCase):
    """Pure keyword rules: no database needed."""

    def test_questions_map_to_the_right_intent(self):
        cases = {
            "What is the status of my latest donation?": "latest_status",
            "How many donations have I completed?": "counts",
            "Show my pending pickups.": "pending_pickups",
            "Why can't I claim this donation?": "why_cant_claim",
            "How many NGOs are awaiting approval?": "pending_ngos",
            "how do I post surplus food": "post_food",
            "how can i withdraw a donation": "withdraw",
            "How does expiry work?": "expiry",
            "How do I register?": "register",
            "how does foodshare work": "about",
            "hello": "greeting",
        }
        for text, intent in cases.items():
            self.assertEqual(intent_handler.detect(text), intent, text)

    def test_unrelated_text_matches_nothing(self):
        for text in ("what is the weather in paris", "asdf qwer", "tell me a joke"):
            self.assertIsNone(intent_handler.detect(text), text)

    def test_listing_number_extraction(self):
        self.assertEqual(intent_handler.extract_listing_id("why can't I claim donation #12"), 12)
        self.assertEqual(intent_handler.extract_listing_id("claim listing 7"), 7)
        self.assertIsNone(intent_handler.extract_listing_id("why can't I claim"))


class DonorQuestions(ChatCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor("Cafe Bloom")
        self.ngo = self.make_ngo("Green Hands")
        self.other = self.make_donor("Other Kitchen")
        services.create_listing(self.other, "Secret Pasta", "9 trays", 4)
        self.first = self.make_listing(self.donor).id
        self.second = services.create_listing(self.donor, "Dal and rice", "10 meals", 4).id
        services.claim_listing(self.ngo, self.first)
        services.mark_picked_up(self.ngo, self.first)
        self.client = self.api_client(self.donor.email)

    def test_latest_donation_status_comes_from_the_database(self):
        text = self.reply(self.client, "What is the status of my latest donation?")
        self.assertIn("Dal and rice", text)
        self.assertIn("Available", text)

    def test_counts_are_this_donors_own_numbers(self):
        text = self.reply(self.client, "How many donations have I completed?")
        self.assertIn("2 donation(s)", text)
        self.assertIn("1 completed", text)

    def test_history_and_claims_never_mention_other_donors(self):
        for question in ("show my donation history", "my active donations", "show my pending pickups"):
            self.assertNotIn("Secret Pasta", self.reply(self.client, question))

    def test_pending_pickup_names_the_claiming_ngo(self):
        services.claim_listing(self.ngo, self.second)
        text = self.reply(self.client, "Show my pending pickups")
        self.assertIn("Green Hands", text)
        self.assertIn("Dal and rice", text)

    def test_knowledge_answers_are_role_aware(self):
        self.assertIn("List surplus food", self.reply(self.client, "How do I post surplus food?"))
        ngo_text = self.reply(self.api_client(self.ngo.email), "How do I post surplus food?")
        self.assertIn("Only donor accounts", ngo_text)

    def test_donor_cannot_read_admin_information(self):
        self.make_ngo("Pending NGO", approved=False)
        text = self.reply(self.client, "How many NGOs are awaiting approval?")
        self.assertIn("administrators only", text)
        self.assertNotIn("Pending NGO", text)


class NgoQuestions(ChatCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor("Cafe Bloom", address="12 Church Street")
        self.ngo = self.make_ngo("Green Hands")
        self.rival = self.make_ngo("Rival NGO")
        self.lid = self.make_listing(self.donor).id
        self.client = self.api_client(self.ngo.email)

    def test_pending_pickups_show_no_private_contact_details(self):
        services.claim_listing(self.ngo, self.lid)
        text = self.reply(self.client, "Show my pending pickups.")
        self.assertIn("Veg biryani", text)
        self.assertIn("Cafe Bloom", text)
        self.assertNotIn(self.donor.email, text)
        self.assertNotIn("12 Church Street", text)

    def test_counts(self):
        services.claim_listing(self.ngo, self.lid)
        self.assertIn("1 still pending", self.reply(self.client, "How many pickups do I have?"))

    def test_approval_status_for_approved_and_pending_ngos(self):
        self.assertIn("approved", self.reply(self.client, "Am I approved?"))
        pending = self.make_ngo("Waiting NGO", approved=False)
        self.assertIn("awaiting administrator approval",
                      self.reply(self.api_client(pending.email), "Am I approved?"))

    def test_why_cant_i_claim_for_an_unapproved_ngo(self):
        pending = self.make_ngo("Waiting NGO", approved=False)
        text = self.reply(self.api_client(pending.email), "Why can't I claim a donation?")
        self.assertIn("awaiting administrator approval", text)

    def test_why_cant_i_claim_does_not_reveal_who_claimed_it(self):
        services.claim_listing(self.rival, self.lid)
        text = self.reply(self.client, f"Why can't I claim donation #{self.lid}?")
        self.assertIn("can't find an available donation", text)
        self.assertNotIn("Rival NGO", text)

    def test_why_cant_i_claim_an_available_donation(self):
        self.assertIn("looks available", self.reply(self.client, f"why can't I claim donation #{self.lid}"))

    def test_ngo_cannot_read_admin_information(self):
        self.assertIn("administrators only", self.reply(self.client, "How many NGOs are awaiting approval?"))
        self.assertIn("administrators only", self.reply(self.client, "show recent activity"))


class AdminQuestions(ChatCase):
    def setUp(self):
        super().setUp()
        services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.make_donor("Cafe Bloom")
        self.make_ngo("Pending NGO", approved=False)
        self.client = self.api_client("boss@t.test", ADMIN_PASSWORD)

    def test_pending_ngos(self):
        text = self.reply(self.client, "How many NGOs are awaiting approval?")
        self.assertIn("1 NGO(s)", text)
        self.assertIn("Pending NGO", text)

    def test_platform_statistics(self):
        text = self.reply(self.client, "Show platform statistics.")
        self.assertIn("1 donor(s)", text)

    def test_how_to_approve(self):
        self.assertIn("Approve", self.reply(self.client, "How do I approve an NGO?"))

    def test_replies_never_contain_credentials(self):
        for question in ("Show platform statistics.", "How many NGOs are awaiting approval?",
                         "show recent activity", "how do I log in"):
            text = self.reply(self.client, question).lower()
            for secret in ("pbkdf2", "scrypt", "password_hash", "boss@t.test"):
                self.assertNotIn(secret, text)


class Visitors(ChatCase):
    def test_general_help_needs_no_login(self):
        self.assertIn("surplus food", self.reply(self.visitor(), "How does FoodShare work?"))

    def test_personal_questions_ask_the_visitor_to_log_in(self):
        self.assertIn("log in", self.reply(self.visitor(), "What is the status of my latest donation?"))

    def test_start_gives_role_specific_suggestions(self):
        donor = self.make_donor()
        data = self.api_client(donor.email).get("/api/v1/chatbot/start").get_json()["data"]
        self.assertEqual(data["role"], "Donor")
        self.assertEqual(data["provider"], "rules+on-device-model")
        self.assertTrue(any("donation" in q for q in data["suggestions"]))
        guest = self.app.test_client().get("/api/v1/chatbot/start").get_json()["data"]
        self.assertIsNone(guest["role"])


class BadInput(ChatCase):
    def test_unknown_question_is_answered_honestly(self):
        text = self.reply(self.visitor(), "what is the weather in paris")
        self.assertIn("not sure", text)

    def test_empty_and_whitespace_messages_are_rejected(self):
        client = self.visitor()
        for message in ("", "   ", "\n\t"):
            self.assertEqual(self.ask(client, message).status_code, 400)

    def test_oversized_message_is_rejected(self):
        client = self.visitor()
        self.assertEqual(self.ask(client, "a" * service.MAX_MESSAGE_CHARS).status_code, 200)
        self.assertEqual(self.ask(client, "a" * (service.MAX_MESSAGE_CHARS + 1)).status_code, 400)

    def test_invalid_requests(self):
        client = self.visitor()
        headers = {"X-CSRFToken": client.token}
        for body in ({"message": 123}, {"message": None}, {"msg": "hi"}, [], "text"):
            res = client.post("/api/v1/chatbot/message", json=body, headers=headers)
            self.assertEqual(res.status_code, 400, body)
        res = client.post("/api/v1/chatbot/message", data="not json", headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_csrf_token_is_required(self):
        res = self.app.test_client().post("/api/v1/chatbot/message", json={"message": "hi"})
        self.assertEqual(res.status_code, 403)

    def test_markup_is_never_echoed_back(self):
        text = self.reply(self.visitor(), "<script>alert(1)</script> how do I register")
        self.assertNotIn("<script>", text)

    def test_rate_limit(self):
        service._limiter.max_calls = 3
        client = self.visitor()
        statuses = [self.ask(client, "hello").status_code for _ in range(5)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])
        self.assertTrue(self.ask(client, "hello").headers.get("Retry-After"))

    def test_rate_limit_is_per_user(self):
        service._limiter.max_calls = 1
        one = self.api_client(self.make_donor().email)
        two = self.api_client(self.make_donor("Second").email)
        self.assertEqual(self.ask(one, "hello").status_code, 200)
        self.assertEqual(self.ask(one, "hello").status_code, 429)
        self.assertEqual(self.ask(two, "hello").status_code, 200)


class ZeroCost(AppTestCase):
    def test_no_external_service_is_used(self):
        """The assistant works with no API key and makes no network calls."""
        source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "chatbot").glob("*.py"))
        for forbidden in ("import requests", "urllib", "http.client", "openai", "anthropic",
                          "os.environ", "getenv", "socket"):
            self.assertNotIn(forbidden, source)

    def test_chat_does_not_change_any_data(self):
        donor = self.make_donor()
        listing = self.make_listing(donor)
        client = self.api_client(donor.email)
        service._limiter.reset()
        for question in ("withdraw my donation", "claim donation", "delete my account"):
            client.post("/api/v1/chatbot/message", json={"message": question},
                        headers={"X-CSRFToken": client.token})
        db.session.expire_all()
        self.assertEqual(self.status_of(listing.id), "Pending")

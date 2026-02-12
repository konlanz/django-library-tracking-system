from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Author, Book, Loan, Member
from .tasks import check_overdue_loans


class LibraryFeatureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_1 = User.objects.create_user(
            username="member1", email="member1@example.com", password="pass1234"
        )
        self.user_2 = User.objects.create_user(
            username="member2", email="member2@example.com", password="pass1234"
        )
        self.member_1 = Member.objects.create(user=self.user_1)
        self.member_2 = Member.objects.create(user=self.user_2)
        self.author = Author.objects.create(first_name="John", last_name="Writer")
        self.book = Book.objects.create(
            title="Test Book",
            author=self.author,
            isbn="1234567890123",
            genre="fiction",
            available_copies=2,
        )

    def test_loan_due_date_default(self):
        loan = Loan.objects.create(book=self.book, member=self.member_1)
        self.assertEqual(
            loan.due_date,
            timezone.localdate() + timedelta(days=settings.LOAN_DURATION_DAYS),
        )

    def test_extend_due_date_success(self):
        loan = Loan.objects.create(book=self.book, member=self.member_1)
        previous_due_date = loan.due_date

        response = self.client.post(
            f"/api/loans/{loan.id}/extend_due_date/",
            {"additional_days": 7},
            format="json",
        )

        loan.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loan.due_date, previous_due_date + timedelta(days=7))

    def test_extend_due_date_rejects_overdue_loan(self):
        loan = Loan.objects.create(book=self.book, member=self.member_1)
        loan.due_date = timezone.localdate() - timedelta(days=1)
        loan.save(update_fields=["due_date"])

        response = self.client.post(
            f"/api/loans/{loan.id}/extend_due_date/",
            {"additional_days": 7},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_check_overdue_loans_sends_email(self):
        overdue_loan = Loan.objects.create(book=self.book, member=self.member_1)
        overdue_loan.due_date = timezone.localdate() - timedelta(days=2)
        overdue_loan.save(update_fields=["due_date"])

        on_time_loan = Loan.objects.create(book=self.book, member=self.member_2)
        on_time_loan.due_date = timezone.localdate() + timedelta(days=2)
        on_time_loan.save(update_fields=["due_date"])

        check_overdue_loans()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Overdue Book Loan Reminder", mail.outbox[0].subject)
        self.assertIn("Test Book", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["member1@example.com"])

    def test_top_active_members_endpoint(self):
        book_2 = Book.objects.create(
            title="Test Book 2",
            author=self.author,
            isbn="1234567890124",
            genre="fiction",
            available_copies=2,
        )

        Loan.objects.create(book=self.book, member=self.member_1, is_returned=False)
        Loan.objects.create(book=book_2, member=self.member_1, is_returned=False)
        Loan.objects.create(book=self.book, member=self.member_2, is_returned=False)

        response = self.client.get("/api/members/top-active/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["id"], self.member_1.id)
        self.assertEqual(response.data[0]["active_loans"], 2)

    def test_books_endpoint_uses_pagination(self):
        for index in range(15):
            Book.objects.create(
                title=f"Book {index}",
                author=self.author,
                isbn=f"9780000000{index:03}",
                genre="fiction",
                available_copies=1,
            )

        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 10)

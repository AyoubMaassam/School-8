from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import json
import datetime

from .models import Student, Teacher, AcademicLevel, Subject, Group, Session, Attendance, ActionLog, StudentGroup
from . import views # To access constants like REGISTRATION_FEE_AMOUNT
from django.contrib.auth.models import User


class BasicSetupTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Academic Levels & Subjects
        self.level_high1 = AcademicLevel.objects.create(name="السنة الأولى ثانوي", category="HIGH")
        self.subject_math = Subject.objects.create(name="رياضيات")

        # Teacher
        self.teacher1 = Teacher.objects.create(
            full_name="أستاذ قدير",
            phone_number="0555123123", subject=self.subject_math
        )

        # Student
        self.student1 = Student.objects.create(
            full_name="طالب مجتهد", phone_number="0777123123",
            birth_day=1, birth_month=1, birth_year=2005, academic_level=self.level_high1
        )

        self.student2 = Student.objects.create(
            full_name="طالبة ذكية", phone_number="0777123124",
            birth_day=5, birth_month=5, birth_year=2006, academic_level=self.level_high1
        )

        # Group
        self.group1 = Group.objects.create(
            name="فوج الرياضيات ثانوي", subject=self.subject_math, teacher=self.teacher1,
            price_per_4_sessions=Decimal('2000.00'), # 500 per session
            session_day=0, session_start_time="14:00:00"
        )
        self.group1.academic_levels.add(self.level_high1)

        # Enroll student with a past date to make sessions billable
        enrollment_date = timezone.now().date() - timezone.timedelta(days=30)
        self.student_group1 = StudentGroup.objects.create(student=self.student1, group=self.group1, enrollment_date=enrollment_date)

        # Sessions for Group1 - ensure they are within the current month for report tests
        today = timezone.now().date()
        # If today is early in the month, create sessions in the past but still within the month
        day_of_month = today.day

        duration = Decimal('1.5')
        self.session1_g1 = Session.objects.create(group=self.group1, date=today.replace(day=2) if day_of_month > 2 else today, start_time="14:00", duration=duration)
        self.session2_g1 = Session.objects.create(group=self.group1, date=today.replace(day=3) if day_of_month > 3 else today, start_time="14:00", duration=duration)
        self.session3_g1 = Session.objects.create(group=self.group1, date=today, start_time="14:00", duration=duration)
        self.session4_g1 = Session.objects.create(group=self.group1, date=today + timezone.timedelta(days=7), start_time="14:00", teacher_attended=False, duration=duration)

        # Attendance
        Attendance.objects.create(student=self.student1, session=self.session1_g1, present=True, student_paid_for_session=True)
        Attendance.objects.create(student=self.student1, session=self.session2_g1, present=False, student_paid_for_session=False)
        Attendance.objects.create(student=self.student1, session=self.session3_g1, present=True, student_paid_for_session=False)

class SessionDeletionTests(BasicSetupTests):
    def test_session_deletion_refunds_paid_students(self):
        student_group = StudentGroup.objects.create(
            student=self.student2, group=self.group1, balance=Decimal('0.00')
        )

        session_to_delete = Session.objects.create(
            group=self.group1, date=timezone.now().date(), start_time="10:00:00", duration=Decimal('1.5')
        )

        Attendance.objects.create(
            student=self.student2, session=session_to_delete, present=True, student_paid_for_session=True
        )

        self.assertEqual(student_group.balance, Decimal('0.00'))
        session_to_delete.delete()
        student_group.refresh_from_db()

        price_per_session = self.group1.price_per_4_sessions / Decimal('4.0')
        self.assertEqual(student_group.balance, price_per_session)

class StudentMonthlyPaymentPageTests(BasicSetupTests):
    def test_get_student_monthly_payment_page_with_group(self):
        response = self.client.get(reverse('student_monthly_payment', args=[self.student1.id]), {'group_id': self.group1.id})
        self.assertEqual(response.status_code, 200)

        # Two sessions are unpaid and not excused
        expected_amount_due = self.group1.price_per_4_sessions / 4 * 2
        self.assertEqual(response.context['gross_amount_due'], expected_amount_due)
        self.assertEqual(response.context['net_amount_due'], expected_amount_due)

    def test_post_process_payment_student_monthly_payment_exact_amount(self):
        amount_to_pay = self.group1.price_per_4_sessions / 4 * 2

        self.client.post(reverse('student_monthly_payment', args=[self.student1.id]), data={
            'action': 'process_payment', 'group_id': self.group1.id, 'amount_paid': str(amount_to_pay)
        })

        att_s2 = Attendance.objects.get(student=self.student1, session=self.session2_g1)
        att_s3 = Attendance.objects.get(student=self.student1, session=self.session3_g1)
        self.assertTrue(att_s2.student_paid_for_session)
        self.assertTrue(att_s3.student_paid_for_session)

    def test_post_process_payment_student_monthly_payment_overpayment(self):
        # Student has 2 unpaid sessions (1000 total). Pay 1500. 500 is overpayment.
        # This 500 should be used to pay for the next available unpaid session (session4_g1).
        amount_to_pay = (self.group1.price_per_4_sessions / 4 * 2) + 500

        self.client.post(
            reverse('student_monthly_payment', args=[self.student1.id]),
            data={'action': 'process_payment', 'group_id': self.group1.id, 'amount_paid': str(amount_to_pay)},
            follow=True
        )

        # Check that the future session is now paid
        att_s4, created = Attendance.objects.get_or_create(student=self.student1, session=self.session4_g1)
        self.assertTrue(att_s4.student_paid_for_session)

        # Check that the remaining balance is now 0
        self.student_group1.refresh_from_db()
        self.assertEqual(self.student_group1.balance, Decimal('0.00'))


    def test_post_process_payment_student_monthly_payment_partial_payment(self):
        amount_to_pay = self.group1.price_per_4_sessions / 4 * 1

        self.client.post(reverse('student_monthly_payment', args=[self.student1.id]), data={
            'action': 'process_payment', 'group_id': self.group1.id, 'amount_paid': str(amount_to_pay)
        })

        att_s2 = Attendance.objects.get(student=self.student1, session=self.session2_g1)
        att_s3 = Attendance.objects.get(student=self.student1, session=self.session3_g1)
        self.assertTrue(att_s2.student_paid_for_session)
        self.assertFalse(att_s3.student_paid_for_session)

class PaymentReportPageTests(BasicSetupTests):
    def setUp(self):
        super().setUp()
        # Move these students' creation date to the past to not interfere with custom date filter test
        self.student1.created_at = timezone.now() - timezone.timedelta(days=60)
        self.student1.registration_fee_paid = True
        self.student1.save()

        self.student2.created_at = timezone.now() - timezone.timedelta(days=60)
        self.student2.registration_fee_paid = True
        self.student2.save()

        self.session1_g1.teacher_compensated = True
        self.session1_g1.teacher_payment_amount = (self.group1.price_per_4_sessions / 4) * views.TEACHER_SESSION_PAY_RATE
        self.session1_g1.save()

    def test_payment_report_loads_and_basic_calculation(self):
        response = self.client.get(reverse('payment_report'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('page_title', response.context)
        self.assertEqual(response.context['page_title'], 'تقرير المدفوعات')

        # In this setup, no students were registered in the current month
        self.assertEqual(response.context['income_from_registration'], Decimal('0.00'))

        expected_session_income = self.group1.price_per_4_sessions / 4
        self.assertEqual(response.context['income_from_sessions'], expected_session_income)

        expected_teacher_expense = (self.group1.price_per_4_sessions / 4) * views.TEACHER_SESSION_PAY_RATE
        self.assertEqual(response.context['total_expenses'], expected_teacher_expense)

    def test_payment_report_custom_date_filter(self):
        filter_start_date = timezone.now().date() - timezone.timedelta(days=5)
        filter_end_date = timezone.now().date()

        new_student = Student.objects.create(
            full_name="Filt Student", phone_number="0123", academic_level=self.level_high1,
            birth_day=1, birth_month=1, birth_year=2000, registration_fee_paid=True
        )
        # Manually update created_at to be timezone-aware and within the filter range
        new_student.created_at = timezone.make_aware(datetime.datetime.combine(filter_start_date, datetime.time(12, 0)))
        new_student.save()

        response = self.client.get(
            reverse('payment_report'),
            {'period': 'custom', 'start_date': filter_start_date.strftime('%Y-%m-%d'), 'end_date': filter_end_date.strftime('%Y-%m-%d')}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['income_from_registration'], views.REGISTRATION_FEE_AMOUNT)

    def test_payment_report_excused_absence_does_not_affect_paid_income(self):
        att_s3 = Attendance.objects.get(student=self.student1, session=self.session3_g1)
        att_s3.student_paid_for_session = True
        att_s3.save()

        att_s2 = Attendance.objects.get(student=self.student1, session=self.session2_g1)
        att_s2.excused_absence = True
        att_s2.save()

        response = self.client.get(reverse('payment_report'))
        self.assertEqual(response.status_code, 200)

        expected_session_income = self.group1.price_per_4_sessions / 4 * 2
        self.assertEqual(response.context['income_from_sessions'], expected_session_income)

class TeacherMonthlyPaymentPageTests(BasicSetupTests):
    def test_calculate_payment_no_sessions_selected(self):
        price_str = "700.00"
        payload = {
            'action': 'calculate_payment',
            'group_id_hidden': self.group1.id,
            'teacher_price_per_session': price_str,
            'sessions_to_pay_ids': [],
        }
        response = self.client.post(reverse('teacher_monthly_payment', args=[self.teacher1.id]), data=payload)
        self.assertEqual(response.status_code, 200) # Should render with message
        messages_list = list(response.context['messages'])
        self.assertTrue(any("الرجاء اختيار حصة واحدة على الأقل للحساب" in str(msg) for msg in messages_list))

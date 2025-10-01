from django.test import TestCase, Client
from django.urls import reverse
import datetime
from django.utils import timezone
from decimal import Decimal
import json
from datetime import date, timedelta
from unittest.mock import patch

from .models import Student, Teacher, AcademicLevel, Subject, Group, Session, Attendance, ActionLog, StudentGroup
from . import views

class BasicSetupTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = date(2025, 10, 15)  # Use a fixed date

        # Academic Levels
        self.level_primary1 = AcademicLevel.objects.create(name="السنة الأولى ابتدائي", category="PRIMARY")
        self.level_middle1 = AcademicLevel.objects.create(name="السنة الأولى متوسط", category="MIDDLE")
        self.level_high1 = AcademicLevel.objects.create(name="السنة الأولى ثانوي", category="HIGH")

        # Subjects
        self.subject_math = Subject.objects.create(name="رياضيات")
        self.subject_arabic = Subject.objects.create(name="لغة عربية")

        # Teacher
        self.teacher1 = Teacher.objects.create(
            full_name="أستاذ قدير",
            phone_number="0555123123", subject=self.subject_math
        )

        # Student
        self.student1 = Student.objects.create(
            full_name="طالب مجتهد", phone_number="0777123123", guardian_phone="0666123123",
            birth_day=1, birth_month=1, birth_year=2005, academic_level=self.level_high1,
            registration_fee_paid=False, created_at=timezone.make_aware(datetime.datetime(2025, 10, 1, 10, 0))
        )
        self.student1.card_number = f"CARD-{self.student1.created_at.year}-{self.student1.id:05d}"
        self.student1.save()

        self.student2 = Student.objects.create(
            full_name="طالبة ذكية", phone_number="0777123124", guardian_phone="0666123124",
            birth_day=5, birth_month=5, birth_year=2006, academic_level=self.level_middle1,
            registration_fee_paid=True, created_at=timezone.make_aware(datetime.datetime(2025, 10, 2, 10, 0))
        )
        self.student2.card_number = f"CARD-{self.student2.created_at.year}-{self.student2.id:05d}"
        self.student2.save()

        # Group
        self.group1 = Group.objects.create(
            name="فوج الرياضيات ثانوي", subject=self.subject_math, teacher=self.teacher1,
            price_per_4_sessions=Decimal('2000.00'), session_day=2,
            session_start_time="14:00:00", session_duration=Decimal('1.5')
        )
        self.group1.academic_levels.add(self.level_high1)
        self.student_group1 = StudentGroup.objects.create(student=self.student1, group=self.group1)

        # Sessions for Group1 with fixed dates
        self.session1_g1 = Session.objects.create(group=self.group1, date=self.today - timedelta(days=14), start_time="14:00:00", duration=Decimal('1.5'), teacher_attended=True)
        self.session2_g1 = Session.objects.create(group=self.group1, date=self.today - timedelta(days=7), start_time="14:00:00", duration=Decimal('1.5'), teacher_attended=True)
        self.session3_g1 = Session.objects.create(group=self.group1, date=self.today, start_time="14:00:00", duration=Decimal('1.5'), teacher_attended=True)
        self.session4_g1 = Session.objects.create(group=self.group1, date=self.today + timedelta(days=7), start_time="14:00:00", duration=Decimal('1.5'))

        # Attendance records
        Attendance.objects.create(student=self.student1, session=self.session1_g1, present=True, student_paid_for_session=True)
        Attendance.objects.create(student=self.student1, session=self.session2_g1, present=False, student_paid_for_session=False)
        Attendance.objects.create(student=self.student1, session=self.session3_g1, present=True, student_paid_for_session=False)

class RegistrationFeeTests(BasicSetupTests):
    def test_registration_fee_constant_value(self):
        self.assertEqual(views.REGISTRATION_FEE_AMOUNT, Decimal('500.00'))

class SessionDeletionTests(BasicSetupTests):
    def test_session_deletion_refunds_paid_students(self):
        student3 = Student.objects.create(full_name="Refund Test", phone_number="0777123125", birth_day=1, birth_month=1, birth_year=2005, academic_level=self.level_high1)
        student_group3 = StudentGroup.objects.create(student=student3, group=self.group1, remaining_sessions=0)
        session_to_delete = Session.objects.create(group=self.group1, date=self.today, start_time="10:00:00", duration=Decimal('1.5'))
        Attendance.objects.create(student=student3, session=session_to_delete, present=True, student_paid_for_session=True)

        self.assertEqual(student_group3.remaining_sessions, 0)
        session_to_delete.delete()
        student_group3.refresh_from_db()
        self.assertEqual(student_group3.remaining_sessions, 1)

class TeacherMonthlyPaymentPageTests(BasicSetupTests):
    def setUp(self):
        super().setUp()
        self.session1_g1.teacher_attended = True
        self.session1_g1.teacher_compensated = False
        self.session1_g1.save()
        self.session2_g1.teacher_attended = True
        self.session2_g1.teacher_compensated = False
        self.session2_g1.save()
        StudentGroup.objects.create(student=self.student2, group=self.group1)
        Attendance.objects.get_or_create(student=self.student2, session=self.session2_g1, defaults={'present': True, 'student_paid_for_session': True})

    def test_calculate_payment_no_sessions_selected(self):
        price_str = "700.00"
        payload = {'action': 'calculate_payment', 'group_id_hidden': self.group1.id, 'teacher_price_per_session': price_str, 'sessions_to_pay_ids': []}
        response = self.client.post(reverse('teacher_monthly_payment', args=[self.teacher1.id]), data=payload, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = list(response.context['messages'])
        self.assertTrue(any("الرجاء اختيار حصة واحدة على الأقل للحساب" in str(msg) for msg in messages_list))

class PaymentReportPageTests(BasicSetupTests):
    def setUp(self):
        super().setUp()
        self.student1.registration_fee_paid = True
        self.student1.save()

    @patch('django.utils.timezone.now')
    def test_payment_report_loads_and_basic_calculation(self, mock_now):
        mock_now.return_value = timezone.make_aware(datetime.datetime(2025, 10, 15, 12, 0))
        start_date = self.today.replace(day=1)
        end_date = self.today
        response = self.client.get(f"{reverse('payment_report')}?period=custom&start_date={start_date}&end_date={end_date}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "التقارير المالية")

        expected_reg_income = views.REGISTRATION_FEE_AMOUNT * 2
        self.assertEqual(response.context['income_from_registration'], expected_reg_income)

        expected_session_income = self.group1.price_per_4_sessions / 4 * 1
        self.assertEqual(response.context['income_from_sessions'], expected_session_income)

    @patch('django.utils.timezone.now')
    def test_payment_report_excused_absence_does_not_affect_paid_income(self, mock_now):
        mock_now.return_value = timezone.make_aware(datetime.datetime(2025, 10, 15, 12, 0))
        att_s3 = Attendance.objects.get(student=self.student1, session=self.session3_g1)
        att_s3.student_paid_for_session = True
        att_s3.save()
        att_s2 = Attendance.objects.get(student=self.student1, session=self.session2_g1)
        att_s2.excused_absence = True
        att_s2.save()

        start_date = self.today - timedelta(days=20)
        end_date = self.today
        response = self.client.get(f"{reverse('payment_report')}?period=custom&start_date={start_date}&end_date={end_date}")
        self.assertEqual(response.status_code, 200)

        expected_session_income = self.group1.price_per_4_sessions / 4 * 2
        self.assertEqual(response.context['income_from_sessions'], expected_session_income)

class StudentMonthlyPaymentPageTests(BasicSetupTests):
    @patch('django.utils.timezone.now')
    def test_get_student_monthly_payment_page_with_group(self, mock_now):
        mock_now.return_value = timezone.make_aware(datetime.datetime(2025, 10, 15, 12, 0))
        response = self.client.get(reverse('student_monthly_payment', args=[self.student1.id]), {'group_id': self.group1.id})
        self.assertEqual(response.status_code, 200)

        expected_amount_due = self.group1.price_per_4_sessions / 4 * 2
        self.assertEqual(response.context['net_amount_due'], expected_amount_due)
        self.assertEqual(response.context['gross_amount_due'], expected_amount_due)

    def test_post_process_payment_student_monthly_payment(self):
        sessions_to_add = 4
        response = self.client.post(reverse('student_monthly_payment', args=[self.student1.id]), data={'action': 'process_payment', 'group_id': self.group1.id, 'sessions_to_add': sessions_to_add})
        self.assertEqual(response.status_code, 302)
        expected_redirect_url = reverse('student_monthly_payment', args=[self.student1.id]) + f'?group_id={self.group1.id}'
        self.assertRedirects(response, expected_redirect_url)
        self.student_group1.refresh_from_db()
        self.assertEqual(self.student_group1.remaining_sessions, sessions_to_add)

class AttendanceApiTests(BasicSetupTests):
    def test_api_record_attendance_success_by_pk(self):
        payload = {'session_id': self.session4_g1.id, 'student_id': self.student1.id}
        response = self.client.post(reverse('api_record_attendance'), data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(Attendance.objects.filter(student=self.student1, session=self.session4_g1, present=True).exists())

from datetime import timedelta
import openpyxl
from django.http import HttpResponse
from django.utils import timezone
import itertools
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
import numpy as np

from core import settings
from evaluations.forms import EmployeeCreationForm, UserCreationFormExtended
from .forms import CompanyRegistrationForm, CompanyWeightsForm, PositionForm, ReassignSubordinatesForm, UserRegistrationForm
from django.contrib.auth.decorators import login_required
from .models import CriterionScore, EvaluationPhase, EvaluationResult, Criterion, EmployeeCriterion, PairwiseComparison, Position, PositionCriterion, User, Company
from django.contrib.auth.forms import PasswordResetForm
from django.http import JsonResponse
from django.db.models import Case, When, Value, IntegerField, Q, Exists, OuterRef, Avg, Sum
from django.core.mail import send_mass_mail
from django.db import transaction

from evaluations import models

def get_latest_available_period(company):
    latest = EvaluationResult.objects.filter(
        employee__company=company, is_archived=False
    ).order_by('-year', '-month').first()
    
    if latest:
        return latest.month, latest.year
    return None, None

@login_required
def start_new_evaluation(request):
    if request.user.role != 'manager':
        return redirect('management_list')

    if request.method == 'POST':
        subordinates = User.objects.filter(manager=request.user)
        
        with transaction.atomic():
            CriterionScore.objects.filter(
                Q(evaluator__in=subordinates) | Q(criterion__employee__in=subordinates),
                is_archived=False
            ).update(is_archived=True)

            EvaluationResult.objects.filter(
                employee__in=subordinates,
                is_archived=False
            ).update(is_archived=True)
            
            EvaluationPhase.objects.filter(
                manager=request.user, 
                is_archived=False
            ).update(is_active=False, is_archived=True)

        messages.success(request, "Старый цикл завершен. Вы можете запустить новый этап оценивания.")
    
    return redirect('management_list')

@login_required
def ratings_view(request):
    user = request.user
    month, year = get_latest_available_period(user.company)
    
    def get_table_data(queryset, title, table_id, pos_id=None):
        results = list(queryset.select_related('employee', 'employee__position'))
        total_score_sum = sum(r.total_score for r in results)
        
        for r in results:
            r.dynamic_share = (r.total_score / total_score_sum * 100) if total_score_sum > 0 else 0
            
        return {
            'title': title,
            'results': results,
            'table_id': table_id,
            'pos_id': pos_id
        }

    tables = []

    if month and year:
        base_qs = EvaluationResult.objects.filter(
            employee__company=user.company, month=month, year=year, is_archived=False
        ).order_by('-total_score')

        if user.role == 'head':
            tables.append(get_table_data(base_qs, "Общий рейтинг компании", "head_all"))

        elif user.role == 'manager':
            managed_positions = Position.objects.filter(user__manager=user).distinct()
            for pos in managed_positions:
                pos_qs = base_qs.filter(employee__manager=user, employee__position=pos)
                tables.append(get_table_data(pos_qs, f"Рейтинг: {pos.name}", "mgr_pos", pos.id))
            
            team_qs = base_qs.filter(employee__manager=user)
            tables.append(get_table_data(team_qs, "Итоговый рейтинг подразделения", "mgr_all"))

        elif user.role == 'employee':
            if user.manager:
                prof_qs = base_qs.filter(employee__manager=user.manager, employee__position=user.position)
                tables.append(get_table_data(prof_qs, f"Ваш рейтинг: {user.position.name}", "emp_prof"))
                
                team_qs = base_qs.filter(employee__manager=user.manager)
                tables.append(get_table_data(team_qs, "Ваш рейтинг в команде", "emp_team"))

    return render(request, 'evaluations/ratings.html', {
        'tables': tables,
        'month': month,
        'year': year,
        'period_name': f"{month}/{year}" if month else "Нет данных"
    })

@login_required
def export_ratings_excel(request):
    table_id = request.GET.get('table_id')
    pos_id = request.GET.get('pos_id')
    
    latest_result = EvaluationResult.objects.filter(
        employee__company=request.user.company, is_archived=False
    ).order_by('-year', '-month').first()
    
    if not latest_result:
        return HttpResponse("Нет данных для экспорта", status=404)
        
    month, year = latest_result.month, latest_result.year
    
    results = EvaluationResult.objects.filter(
        employee__company=request.user.company,
        month=month,
        year=year,
        is_archived=False
    ).select_related('employee', 'employee__position')

    
    report_title = "Рейтинг" 
    
    if table_id == "company_all" and request.user.role == 'head':
        report_title = "Общий рейтинг компании"
        
    elif table_id == "manager_pos":
        pos = get_object_or_404(Position, id=pos_id)
        results = results.filter(employee__manager=request.user, employee__position=pos)
        report_title = f"Рейтинг по должности - {pos.name}"
        
    elif table_id == "manager_all":
        results = results.filter(employee__manager=request.user)
        report_title = "Итоговый рейтинг подразделения"
        
    elif table_id == "emp_prof":
        results = results.filter(
            employee__manager=request.user.manager, 
            employee__position=request.user.position
        )
        report_title = f"Рейтинг должности - {request.user.position.name if request.user.position else '-'}"
        
    elif table_id == "emp_team":
        results = results.filter(employee__manager=request.user.manager)
        report_title = "Рейтинг команды"
    
    else:
        if request.user.role == 'employee':
            results = results.filter(employee__manager=request.user.manager)
        elif request.user.role == 'manager':
            results = results.filter(employee__manager=request.user)

    results = results.order_by('-total_score')

    total_score_sum = sum(r.total_score for r in results)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Рейтинг {month}-{year}"

    ws.append([report_title])
    ws.append([f"Период: {month}/{year}"])
    ws.append([]) 
    
    columns = ['Место', 'ФИО', 'Должность', 'Индекс эффективности', 'Коэффициент вклада (%)']
    ws.append(columns)

    for i, res in enumerate(results, 1):
        dynamic_share = (res.total_score / total_score_sum * 100) if total_score_sum > 0 else 0
        
        ws.append([
            i, 
            res.employee.get_full_name(), 
            res.employee.position.name if res.employee.position else "-", 
            res.total_score,
            f"{dynamic_share:.2f}%" 
        ])

    for column_cells in ws.columns:
        length = max(len(str(cell.value)) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = length + 2

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"ratings_{table_id}_{month}_{year}.xlsx"
    response['Content-Disposition'] = f'attachment; filename={filename}'
    
    wb.save(response)
    return response

@login_required
def add_user_logic(request, role_type):
    if request.method == 'POST':
        form = UserCreationFormExtended(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.company = request.user.company
            user.role = role_type
            user.set_unusable_password() 
            user.save()

            current_site = get_current_site(request)
            subject = 'Приглашение в систему оценки персонала'
            message = render_to_string('evaluations/acc_active_email.html', {
                'user': user,
                'domain': current_site.domain,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            })
            send_mail(
                subject, 
                message, 
                settings.DEFAULT_FROM_EMAIL, 
                [user.email], 
                fail_silently=True
            )
            
            return redirect('management_list')
    else:
        form = UserCreationFormExtended()
    
    role_name = "менеджера" if role_type == 'manager' else "сотрудника"
    return render(request, 'evaluations/add_user.html', {'form': form, 'role_name': role_name})

def trigger_password_reset(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            user = User.objects.get(username=username)
            if user.email:
                form = PasswordResetForm({'email': user.email})
                if form.is_valid():
                    form.save(
                        request=request,
                        use_https=request.is_secure(),
                        email_template_name='registration/password_reset_email.html', 
                        subject_template_name='registration/password_reset_subject.txt',
                    )
                    return JsonResponse({'status': 'success'})
            return JsonResponse({'status': 'no_email'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'not_found'})
    return JsonResponse({'status': 'error'})

def home(request):

    content = {
        "hero": {
            "title": "Умная мотивация ваших сотрудников",
            "subtitle": "Объективная оценка по методу Саати и прозрачное распределение бонусного фонда",
            "button_text": "Попробовать демо",
            "register_text": "Регистрация компании"
        },
        "features": [
            {
                "title": "Метод анализа иерархий",
                "desc": "Математически обоснованный подход к сравнению критериев, исключающий субъективность",
                "icon": "bi-diagram-3"
            },
            {
                "title": "Прозрачные KPI",
                "desc": "Сотрудники видят свою формулу успеха и понимают, как формируется их премия",
                "icon": "bi-eye"
            },
            {
                "title": "Дашборды",
                "desc": "Визуализация результатов команды для принятия решений",
                "icon": "bi-bar-chart"
            }
        ],
        "stats": [
            {"value": "1M+", "label": "Распределенных премий"},
            {"value": "500+", "label": "Активных сотрудников"},
            {"value": "98%", "label": "Точность оценки"}
        ]
    }
    return render(request, 'evaluations/home.html', context=content)

@login_required
def add_employee(request):
    if request.user.role not in ['head', 'manager']:
        return redirect('home')
    
    if request.method == 'POST':
        form = UserCreationFormExtended(request.POST, hide_position=False, company=request.user.company)
        if form.is_valid():
            user = form.save(commit=False)
            user.company = request.user.company
            user.role = 'employee'
            
            user.manager = request.user 
            
            user.set_unusable_password()
            user.save()

            current_site = get_current_site(request)
            subject = 'Приглашение в систему (Сотрудник)'
            message = render_to_string('evaluations/acc_active_email.html', {
                'user': user,
                'domain': current_site.domain,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            })

            print("\n" + "="*50)
            print(f"ПИСЬМО ДЛЯ СОТРУДНИКА ({user.get_full_name()}):")
            print(message)
            print("="*50 + "\n")

            from django.conf import settings
            send_mail(
                subject, 
                message, 
                settings.DEFAULT_FROM_EMAIL, 
                [user.email], 
                fail_silently=True
            )
            return redirect('management_list')
    else:
        form = UserCreationFormExtended(hide_position=False, company=request.user.company)
    
    return render(request, 'evaluations/add_user.html', {'form': form, 'role_name': 'сотрудника'})

def register_company(request):
    if request.method == 'POST':
        c_form = CompanyRegistrationForm(request.POST)
        u_form = UserRegistrationForm(request.POST)
        
        if c_form.is_valid() and u_form.is_valid():
 
            new_company = c_form.save()
      
            new_user = u_form.save(commit=False)
            new_user.set_password(u_form.cleaned_data['password'])
            new_user.company = new_company
            new_user.role = 'head'  
            new_user.save()
            
            login(request, new_user)
            return redirect('home')
    else:
        c_form = CompanyRegistrationForm()
        u_form = UserRegistrationForm()
    
    return render(request, 'evaluations/register.html', {
        'c_form': c_form, 'u_form': u_form
    })

def send_evaluation_notification(request, employee):

    current_site = get_current_site(request)
    subject = 'Вам назначены критерии оценки'
    
    html_message = render_to_string('evaluations/evaluation_notification_email.html', {
        'user': employee,
        'domain': current_site.domain,
    })
    
    send_mail(
        subject,
        '', 
        settings.DEFAULT_FROM_EMAIL,
        [employee.email],
        html_message=html_message,
        fail_silently=True
    )
    

@login_required
def dashboard(request):
    if request.user.role in ['head', 'manager']:
        return redirect('management_list')
    
    user = request.user
    
    if user.manager and user.position:
        check_and_finalize_position(user.position, user.manager, request)

    criteria = EmployeeCriterion.objects.filter(employee=user).order_by('name')
    eval_result = EvaluationResult.objects.filter(employee=user, is_archived=False).first()
    
    first_crit = criteria.first()
    is_employee_evaluated = first_crit.employee_evaluated if first_crit else False

    active_phase = EvaluationPhase.objects.filter(
        manager=user.manager,
        position=user.position,
        is_active=True,
        is_archived=False
    ).first()

    peers_to_evaluate = []
    evaluation_completed = False

    if active_phase:
        peers = User.objects.filter(
            company=user.company,
            position=user.position,
            manager=user.manager,
            role='employee'
        ).order_by('last_name')

        for peer in peers:
            is_rated = CriterionScore.objects.filter(
                evaluator=user, 
                criterion__employee=peer,
                is_archived=False
            ).exists()
            
            peers_to_evaluate.append({
                'user': peer,
                'is_rated': is_rated
            })

        if peers_to_evaluate:
            total_count = len(peers_to_evaluate)
            rated_count = sum(1 for p in peers_to_evaluate if p['is_rated'])
            if rated_count == total_count:
                evaluation_completed = True

    return render(request, 'evaluations/employee_dashboard.html', {
        'user': user,
        'criteria': criteria,
        'eval_result': eval_result,
        'is_employee_evaluated': is_employee_evaluated,
        'is_evaluation_open': bool(active_phase), 
        'peers_to_evaluate': peers_to_evaluate,
        'evaluation_completed': evaluation_completed 
    })

@login_required
def add_manager(request):
    if request.user.role != 'head':
        return redirect('home')
    
    if request.method == 'POST':
        form = UserCreationFormExtended(request.POST, hide_position=True, company=request.user.company)
        if form.is_valid():
            user = form.save(commit=False)
            user.company = request.user.company
            user.role = 'manager'
            
            pos_manager, created = Position.objects.get_or_create(
                company=request.user.company, 
                name="Менеджер"
            )
            user.position = pos_manager
            user.save()

            current_site = get_current_site(request)
            subject = 'Приглашение в систему (Менеджер)'
            message = render_to_string('evaluations/acc_active_email.html', {
                'user': user,
                'domain': current_site.domain,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            })

            print("\n" + "="*50)
            print("ПИСЬМО ДЛЯ МЕНЕДЖЕРА:")
            print(message)
            print("="*50 + "\n")

            send_mail(
                subject, 
                message, 
                settings.DEFAULT_FROM_EMAIL, 
                [user.email], 
                fail_silently=True
            )
            return redirect('management_list')
        else:
            print("ОШИБКИ ФОРМЫ МЕНЕДЖЕРА:", form.errors) 
    else:
        form = UserCreationFormExtended(hide_position=True, company=request.user.company)
    
    return render(request, 'evaluations/add_user.html', {'form': form, 'role_name': 'менеджера'})

@login_required
def management_list(request):
    positions = []
    pos_form = PositionForm()
    users = []
    weights_form = None  
    ready_positions = [] 
    active_phases = []
    completed_phases = [] 
    now = timezone.now()  
    title = ""
    add_label = ""
    add_url = ""
    can_start_new_cycle = False 

    if request.user.role == 'head':
        users = User.objects.filter(company=request.user.company, role='manager').order_by('last_name')
        positions = Position.objects.filter(company=request.user.company).prefetch_related('base_criteria').order_by('name')
        weights_form = CompanyWeightsForm(instance=request.user.company)

        if request.method == 'POST':
            if 'update_weights' in request.POST:
                weights_form = CompanyWeightsForm(request.POST, instance=request.user.company)
                if weights_form.is_valid():
                    company = weights_form.save(commit=False)
                    company.weight_manager = weights_form.cleaned_data['weight_manager'] / 100
                    company.weight_self = weights_form.cleaned_data['weight_self'] / 100
                    company.weight_peer = weights_form.cleaned_data['weight_peer'] / 100
                    company.save()
                    return redirect('management_list')

            if 'add_position' in request.POST:
                pos_form = PositionForm(request.POST)
                if pos_form.is_valid():
                    new_pos = pos_form.save(commit=False)
                    new_pos.company = request.user.company
                    new_pos.save()
                    return redirect('management_list')
            
            elif 'add_pos_criterion' in request.POST:
                pos_id = request.POST.get('pos_id')
                crit_name = request.POST.get('crit_name')
                if pos_id and crit_name:
                    pos = get_object_or_404(Position, id=pos_id, company=request.user.company)
                    PositionCriterion.objects.create(position=pos, name=crit_name)
                    return redirect(reverse('management_list') + f'?opened_pos={pos_id}')
            
            elif 'delete_pos_criterion' in request.POST:
                crit_id = request.POST.get('criterion_id')
                criterion = get_object_or_404(PositionCriterion, id=crit_id, position__company=request.user.company)
                pos_id = criterion.position.id
                criterion.delete()
                return redirect(reverse('management_list') + f'?opened_pos={pos_id}')

        title = "Управление менеджерами и должностями"
        add_label = "Добавить менеджера"
        add_url = "add_manager"

    elif request.user.role == 'manager':
        active_to_check = EvaluationPhase.objects.filter(manager=request.user, is_active=True, is_archived=False)
        for phase in active_to_check:
            check_and_finalize_position(phase.position, request.user, request)

        base_users = User.objects.filter(company=request.user.company, role='employee', manager=request.user)
        
        users = base_users.annotate(
            is_evaluation_active=Exists(EvaluationPhase.objects.filter(
                manager=request.user, position=OuterRef('position_id'), is_active=True, is_archived=False
            )),
            manager_has_rated=Exists(CriterionScore.objects.filter(
                evaluator=request.user, is_archived=False, criterion__employee=OuterRef('pk')
            )),
            priority=Case(
                When(criteria_confirmed=False, then=Value(1)),
                When(
                    Q(criteria_confirmed=True) & 
                    ~Exists(EmployeeCriterion.objects.filter(employee=OuterRef('pk'), manager_evaluated=True)), 
                    then=Value(2)
                ),
                When(
                    Exists(EmployeeCriterion.objects.filter(employee=OuterRef('pk'), manager_evaluated=True)) &
                    ~Exists(EmployeeCriterion.objects.filter(employee=OuterRef('pk'), employee_evaluated=True)),
                    then=Value(3)
                ),
                default=Value(4),
                output_field=IntegerField(),
            )
        ).order_by('priority', 'last_name')

        has_active_phases = active_to_check.exists()
        all_employees_finished_ahp = not users.filter(priority__lt=4).exists()
        
        if all_employees_finished_ahp and not has_active_phases:
            can_start_new_cycle = True

        month_phases = EvaluationPhase.objects.filter(
            manager=request.user,
            is_archived=False
        )
        active_phases = list(month_phases.filter(is_active=True))
        completed_phases = month_phases.filter(is_active=False)

        for phase in active_phases:
            group_emps = base_users.filter(position=phase.position)
            potential_evaluators = [request.user] + list(group_emps)
            evaluators_status = []
            
            for person in potential_evaluators:
                actual_scores = CriterionScore.objects.filter(
                    evaluator=person,
                    criterion__employee__position=phase.position,
                    is_archived=False
                ).count()
                
                total_to_rate = 0
                for target_emp in group_emps:
                    total_to_rate += target_emp.assigned_criteria.count()
                
                evaluators_status.append({
                    'name': person.get_full_name() if person != request.user else "Вы (Менеджер)",
                    'progress': actual_scores,
                    'total': total_to_rate,
                    'is_finished': actual_scores >= total_to_rate and total_to_rate > 0
                })
            phase.reports = evaluators_status

        assigned_pos_ids = base_users.values_list('position_id', flat=True).distinct()
        my_positions = Position.objects.filter(id__in=assigned_pos_ids)
        active_pos_ids = [p.position_id for p in active_phases]
        completed_pos_ids = completed_phases.values_list('position_id', flat=True)

        for pos in my_positions:
            if pos.id in active_pos_ids or pos.id in completed_pos_ids:
                continue
            
            subordinates = base_users.filter(position=pos)
            group_ready = subordinates.exists()
            for sub in subordinates:
                if not sub.criteria_confirmed or not sub.assigned_criteria.exists() or \
                   sub.assigned_criteria.filter(weight=0.0).exists():
                    group_ready = False
                    break
            if group_ready:
                ready_positions.append(pos)

        if request.method == 'POST' and 'launch_evaluation' in request.POST:
            pos_id = request.POST.get('position_id')
            pos_obj = get_object_or_404(Position, id=pos_id)
            
            if not EvaluationPhase.objects.filter(manager=request.user, position=pos_obj, is_active=True, is_archived=False).exists():
                EvaluationPhase.objects.create(manager=request.user, position=pos_obj, is_active=True, is_archived=False)
                send_evaluation_launch_emails(request, pos_obj, request.user)
                messages.success(request, f"Оценка для должности {pos_obj.name} запущена.")
            return redirect('management_list')

        title = "Управление сотрудниками"
        add_label = "Добавить сотрудника"
        add_url = "add_employee"
    
    else:
        return redirect('dashboard')

    return render(request, 'evaluations/management_list.html', {
        'users_list': users,
        'positions': positions,
        'pos_form': pos_form,
        'weights_form': weights_form,
        'ready_positions': ready_positions,
        'active_phases': active_phases,
        'completed_phases': completed_phases,
        'now': now,
        'title': title,
        'add_label': add_label,
        'add_url': add_url,
        'can_start_new_cycle': can_start_new_cycle, 
    })

@login_required
def manage_criteria(request, employee_id):
    employee = get_object_or_404(User, id=employee_id, company=request.user.company)
    
    if employee.position:
        base_pos_criteria = PositionCriterion.objects.filter(position=employee.position)
        for bp_crit in base_pos_criteria:
            EmployeeCriterion.objects.get_or_create(
                employee=employee, 
                name=bp_crit.name,
                is_individual=False
            )
    
    all_criteria = employee.assigned_criteria.all().order_by('is_individual', 'name')
    
    is_evaluation_open = EvaluationPhase.objects.filter(
        manager=request.user,
        position=employee.position,
        is_active=True,
        is_archived=False
    ).exists()

    is_evaluated = all_criteria.filter(manager_evaluated=True).exists()
    manager_has_rated = CriterionScore.objects.filter(
        evaluator=request.user,
        criterion__employee=employee,
        is_archived=False
    ).exists()

    error_message = None

    if request.method == 'POST':
        if is_evaluation_open:
            error_message = "Нельзя изменять критерии, пока идет активная фаза оценки по этой должности."
        else:
            if 'confirm_criteria' in request.POST:
                if all_criteria.count() >= 2:
                    employee.criteria_confirmed = True
                    employee.save()
                    return redirect('manage_criteria', employee_id=employee.id)
                else:
                    error_message = "Для оценки требуется минимум 2 критерия."
                
            elif 'reset_criteria' in request.POST:
                all_criteria.update(weight=0.0, manager_evaluated=False, employee_evaluated=False)
                employee.criteria_confirmed = False 
                employee.save()
                PairwiseComparison.objects.filter(employee=employee).delete()
                CriterionScore.objects.filter(criterion__employee=employee, is_archived=False).delete()
                return redirect('manage_criteria', employee_id=employee.id)

            if not employee.criteria_confirmed:
                if 'add_individual' in request.POST:
                    individual_count = all_criteria.filter(is_individual=True).count()
                    if individual_count < 2:
                        crit_name = request.POST.get('criterion_name')
                        if crit_name:
                            EmployeeCriterion.objects.create(
                                employee=employee, 
                                name=crit_name, 
                                is_individual=True
                            )
                            return redirect('manage_criteria', employee_id=employee.id)
                    else:
                        error_message = "Нельзя добавить более 2-х индивидуальных критериев."

                elif 'delete_individual' in request.POST:
                    crit_id = request.POST.get('criterion_id')
                    criterion = get_object_or_404(
                        EmployeeCriterion, id=crit_id, employee=employee, is_individual=True
                    )
                    criterion.delete()
                    return redirect('manage_criteria', employee_id=employee.id)

    individual_count = all_criteria.filter(is_individual=True).count()

    return render(request, 'evaluations/manage_criteria.html', {
        'employee': employee,
        'criteria': all_criteria,
        'error_message': error_message,
        'individual_count': individual_count,
        'is_evaluated': is_evaluated,
        'is_evaluation_open': is_evaluation_open,
        'manager_has_rated': manager_has_rated 
    })

def calculate_ahp_weights(matrix):
    matrix = np.array(matrix)
    eig_vals, eig_vecs = np.linalg.eig(matrix)
    max_eig_vec = eig_vecs[:, eig_vals.argmax()].real
    weights = max_eig_vec / max_eig_vec.sum()
    return weights.tolist()

def get_weights_from_ahp(employee, evaluator, criteria_list):
    n = len(criteria_list)
    matrix = np.ones((n, n))
    criteria_ids = [c.id for c in criteria_list]
    
    comparisons = PairwiseComparison.objects.filter(employee=employee, evaluator=evaluator)
    for comp in comparisons:
        try:
            idx1 = criteria_ids.index(comp.criterion1.id)
            idx2 = criteria_ids.index(comp.criterion2.id)
            matrix[idx1, idx2] = comp.value
            matrix[idx2, idx1] = 1 / comp.value
        except ValueError:
            continue
    
    return calculate_ahp_weights(matrix)

def send_evaluation_launch_emails(request, position, manager):
    current_site = get_current_site(request)
    domain = current_site.domain
    
    subordinates = User.objects.filter(position=position, manager=manager, role='employee')
    
    for emp in subordinates:
        html_message = render_to_string('evaluations/eval_launch_employee.html', {
            'user': emp,
            'domain': domain,
        })
        
        send_mail(
            subject='Старт этапа взаимной оценки ',
            message=f'Здравствуйте! Руководитель запустил этап оценки. Войдите в систему: http://{domain}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[emp.email],
            html_message=html_message,
            fail_silently=True
        )

    html_manager = render_to_string('evaluations/eval_launch_manager.html', {
        'manager': manager,
        'position': position,
        'domain': domain,
    })
    
    send_mail(
        subject=f'Сессия оценки запущена: {position.name}',
        message='Вы запустили оценку для своей группы.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[manager.email],
        html_message=html_manager,
        fail_silently=True
    )

@login_required
def compare_criteria(request, employee_id):
    employee = get_object_or_404(User, id=employee_id, company=request.user.company)
    current_criteria = employee.assigned_criteria.all().order_by('name')
    
    if request.user.role in ['head', 'manager']:
        if current_criteria.filter(manager_evaluated=True).exists():
            return redirect('manage_criteria', employee_id=employee.id)
    else:
        if current_criteria.filter(employee_evaluated=True).exists():
            return redirect('dashboard')

    if current_criteria.count() < 2:
        return redirect('manage_criteria', employee_id=employee.id)

    unique_presets = []
    if request.user.role in ['head', 'manager']:
        seen_weight_combinations = []
        current_names_set = set(c.name for c in current_criteria)
        others_with_evals = User.objects.filter(
            company=request.user.company, assigned_criteria__manager_evaluated=True
        ).exclude(id=employee.id).distinct()

        for other_user in others_with_evals:
            other_criteria = other_user.assigned_criteria.all().order_by('name')
            if current_names_set == set(oc.name for oc in other_criteria):
                weights_map = {oc.name: oc.weight for oc in other_criteria}
                if weights_map not in seen_weight_combinations:
                    seen_weight_combinations.append(weights_map)
                    unique_presets.append({
                        'id': len(unique_presets) + 1,
                        'display': weights_map,
                        'serialized': "|".join([f"{n}:{w}" for n, w in weights_map.items()])
                    })

    if request.method == 'POST':
        if 'apply_preset' in request.POST:
            serialized_data = request.POST.get('preset_data')
            weight_dict = dict(item.split(":") for item in serialized_data.split("|"))
            for crit in current_criteria:
                crit.weight = float(weight_dict[crit.name]) 
                crit.manager_evaluated = True
                crit.save()
            send_evaluation_notification(request, employee)
            return redirect('management_list')

        else:
            pairs = list(itertools.combinations(current_criteria, 2))
            PairwiseComparison.objects.filter(employee=employee, evaluator=request.user).delete()
            
            for c1, c2 in pairs:
                val_raw = request.POST.get(f'pair_{c1.id}_{c2.id}')
                if val_raw:
                    PairwiseComparison.objects.create(
                        employee=employee, evaluator=request.user,
                        criterion1=c1, criterion2=c2, value=float(val_raw)
                    )

            if request.user.role in ['head', 'manager']:
                current_criteria.update(manager_evaluated=True)
                send_evaluation_notification(request, employee)
            else:
                current_criteria.update(employee_evaluated=True)

            first_crit = current_criteria.first()
            if first_crit.manager_evaluated and first_crit.employee_evaluated:
                criteria_list = list(current_criteria)
                
                has_manager_comparisons = PairwiseComparison.objects.filter(
                    employee=employee, evaluator__role__in=['head', 'manager']
                ).exists()
                
                if has_manager_comparisons:
                    manager_weights = get_weights_from_ahp(employee, request.user, criteria_list)
                else:
                    manager_weights = [c.weight for c in criteria_list]

                employee_weights = get_weights_from_ahp(employee, employee, criteria_list)

                for i, crit in enumerate(criteria_list):
                    final_w = (manager_weights[i] + employee_weights[i]) / 2
                    crit.weight = round(final_w, 4)
                    crit.save()

            return redirect('dashboard' if request.user.role == 'employee' else 'management_list')

    pairs = list(itertools.combinations(current_criteria, 2))
    return render(request, 'evaluations/compare_criteria.html', {
        'employee': employee,
        'pairs': pairs,
        'unique_presets': unique_presets,
        'saaty_scale': [(1,'Равно'),(3,'Умерено'),(5,'Сильно'),(7,'Очень'),(9,'Абсолютно')]
    })

@login_required
def start_position_evaluation(request, position_id):
    if request.user.role not in ['head', 'manager']:
        return redirect('home')
        
    position = get_object_or_404(Position, id=position_id, company=request.user.company)
    employees = User.objects.filter(position=position, role='employee')
    
    for emp in employees:
        if not EmployeeCriterion.objects.filter(employee=emp, manager_evaluated=True, employee_evaluated=True).exists():
            return redirect('management_list')

    current_site = get_current_site(request)
    login_url = f"http://{current_site.domain}{reverse('login')}"
    
    emails = []
    for emp in employees:
        msg = (
            'Начало этапа взаимной оценки',
            f'Здравствуйте, {emp.first_name}! Все веса критериев для вашей должности зафиксированы. Пожалуйста, перейдите в систему для оценки коллег: {login_url}',
            settings.DEFAULT_FROM_EMAIL,
            [emp.email]
        )
        emails.append(msg)
    
    msg_mgr = (
        'Пора оценить сотрудников',
        f'Здравствуйте! Сотрудники должности "{position.name}" готовы к оценке. Перейдите по ссылке: {login_url}',
        settings.DEFAULT_FROM_EMAIL,
        [request.user.email]
    )
    emails.append(msg_mgr)
    
    send_mass_mail(tuple(emails))
    return redirect('management_list')

@login_required
def peer_evaluation_list(request):
    if request.user.role != 'employee':
        return redirect('management_list')
    
    peers = User.objects.filter(
        company=request.user.company, 
        position=request.user.position,
        manager=request.user.manager, 
        role='employee'
    )
    
    return render(request, 'evaluations/peer_list.html', {
        'peers': peers,
        'manager': request.user.manager 
    })

from django.utils import timezone
from django.db.models import Avg, Sum

from django.db import transaction
from django.utils import timezone
from django.db.models import Avg, Sum

def check_and_finalize_position(position, manager, request):
    active_phase = EvaluationPhase.objects.filter(
        manager=manager, 
        position=position, 
        is_active=True,
        is_archived=False
    ).first()

    if not active_phase:
        return False

    employees = User.objects.filter(position=position, manager=manager, role='employee')
    total_emp_count = employees.count()
    if total_emp_count == 0:
        return False
        
    expected_scores = total_emp_count + 1 
    all_finished = True

    for emp in employees:
        emp_criteria = emp.assigned_criteria.all()
        if not emp_criteria.exists():
            all_finished = False
            break
        for crit in emp_criteria:
            if CriterionScore.objects.filter(criterion=crit, is_archived=False).count() < expected_scores:
                all_finished = False
                break
        if not all_finished:
            break

    if all_finished:
        with transaction.atomic():
            updated_rows = EvaluationPhase.objects.filter(
                id=active_phase.id, 
                is_active=True
            ).update(is_active=False)

            if updated_rows == 0:
                return False

            company = manager.company
            current_site = get_current_site(request)
            now = timezone.now()

            for emp in employees:
                final_index = 0
                for crit in emp.assigned_criteria.all():
                    m_score = CriterionScore.objects.filter(
                        criterion=crit, evaluator__role__in=['manager', 'head'], is_archived=False
                    ).aggregate(Avg('score'))['score__avg'] or 0
                    
                    s_score = CriterionScore.objects.filter(
                        criterion=crit, evaluator=emp, is_archived=False
                    ).aggregate(Avg('score'))['score__avg'] or 0
                    
                    p_score = CriterionScore.objects.filter(
                        criterion=crit, is_archived=False
                    ).exclude(evaluator=emp).exclude(evaluator__role__in=['manager', 'head']).aggregate(Avg('score'))['score__avg'] or 0
                    
                    weighted_val = (
                        (m_score * company.weight_manager) + (s_score * company.weight_self) + (p_score * company.weight_peer)
                    )
                    final_index += (crit.weight * weighted_val)
                
                
                EvaluationResult.objects.filter(
                    employee=emp, month=now.month, year=now.year,is_archived=False
                ).update(is_archived=True)

                res = EvaluationResult.objects.create(
                    employee=emp, month=now.month, year=now.year, total_score=round(final_index, 4), is_archived=False 
                )
                
                try:
                    html_message = render_to_string('evaluations/eval_completed_employee.html', {
                        'user': emp,
                        'domain': current_site.domain,
                    })
                    send_mail(
                        'Оценка успешно завершена!',
                        f'Здравствуйте, {emp.first_name}! Процесс оценки за {now.month}/{now.year} завершен.',
                        settings.DEFAULT_FROM_EMAIL,
                        [emp.email],
                        html_message=html_message,
                        fail_silently=True
                    )
                except Exception as e:
                    print(f"Ошибка почты для {emp.email}: {e}")

            total_sum = EvaluationResult.objects.filter(
                employee__company=company,
                month=now.month,
                year=now.year,
                is_archived=False
            ).aggregate(total=Sum('total_score'))['total'] or 0
            
            if total_sum > 0:
                current_active_results = EvaluationResult.objects.filter(
                    employee__company=company,
                    month=now.month,
                    year=now.year,
                    is_archived=False
                )
                for result in current_active_results:
                    result.share = round(result.total_score / total_sum, 4)
                    result.save()
        
        return True
    
    return False

@login_required
def rate_employee(request, employee_id):
    target = get_object_or_404(User, id=employee_id, company=request.user.company)
    criteria = target.assigned_criteria.all()
    
    if request.method == 'POST':
        for crit in criteria:
            val = request.POST.get(f'score_{crit.id}')
            if val:
                CriterionScore.objects.update_or_create(
                    criterion=crit, evaluator=request.user, is_archived=False,
                    defaults={'score': int(val)}
                )
        
        check_and_finalize_position(target.position, target.manager, request)
        
        if request.user.role in ['head', 'manager']:
            return redirect('management_list')
        return redirect('dashboard')

    return render(request, 'evaluations/rate_form.html', {
        'target': target,
        'criteria': criteria,
        'range': range(1, 11)
    })

@login_required
def delete_employee(request, employee_id):
    employee = get_object_or_404(User, id=employee_id, company=request.user.company, role='employee')
    
    active_phases = EvaluationPhase.objects.filter(
        position=employee.position,
        manager=employee.manager,
        is_active=True,
        is_archived=False
    ).exists()

    if active_phases:
        messages.error(request, f"Нельзя удалить сотрудника {employee.get_full_name()}, пока идет активная фаза оценки его должности.")
        return redirect('management_list')

    if request.method == 'POST':
        employee.delete()
        messages.success(request, "Сотрудник успешно удален.")
        return redirect('management_list')
    
    return render(request, 'evaluations/confirm_delete.html', {'target': employee})

@login_required
def delete_manager(request, manager_id):
    manager_to_delete = get_object_or_404(User, id=manager_id, company=request.user.company, role='manager')

    if EvaluationPhase.objects.filter(manager=manager_to_delete, is_active=True, is_archived=False).exists():
        messages.error(request, "Нельзя удалить менеджера с активными фазами оценки. Сначала завершите или архивируйте их.")
        return redirect('management_list')

    subordinates = manager_to_delete.subordinates.all()
    
    if request.method == 'POST':
        form = ReassignSubordinatesForm(request.POST, company=request.user.company, exclude_user=manager_to_delete)
        if form.is_valid():
            new_manager = form.cleaned_data['new_manager']
            
            with transaction.atomic():
                subordinates.update(manager=new_manager)
                manager_to_delete.delete()
            
            messages.success(request, f"Менеджер удален. Команда переведена под управление {new_manager.get_full_name()}.")
            return redirect('management_list')
    else:
        form = ReassignSubordinatesForm(company=request.user.company, exclude_user=manager_to_delete)

    return render(request, 'evaluations/reassign_manager.html', {
        'manager': manager_to_delete,
        'subordinates': subordinates,
        'form': form
    })
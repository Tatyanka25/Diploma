import itertools
from pyexpat.errors import messages
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
from .forms import CompanyRegistrationForm, PositionForm, UserRegistrationForm
from django.contrib.auth.decorators import login_required
from .models import EvaluationResult, Criterion, EmployeeCriterion, PairwiseComparison, Position, PositionCriterion, User, Company

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
                fail_silently=False
            )
            
            return redirect('management_list')
    else:
        form = UserCreationFormExtended()
    
    role_name = "менеджера" if role_type == 'manager' else "сотрудника"
    return render(request, 'evaluations/add_user.html', {'form': form, 'role_name': role_name})


def get_footer_data():
    return {
        "about": "Система многокритериальной оценки на базе метода МАИ. Помогаем бизнесу распределять ресурсы справедливо.",
        "quick_links": [
            {"name": "Главная", "url": "/"},
            {"name": "Методология", "url": "#"},
            {"name": "Поддержка", "url": "#"},
        ],
        "contacts": {
            "email": "support@hr-system.ru",
            "phone": "8 (800) 555-35-35",
            "address": "Москва, Инновационный центр Сколково"
        },
        "social": ["Facebook", "LinkedIn", "Telegram"]
    }

def home(request):

    content = {
        "hero": {
            "title": "Умная мотивация ваших сотрудников",
            "subtitle": "Объективная оценка по методу Саати и прозрачное распределение бонусного фонда.",
            "button_text": "Попробовать демо",
            "register_text": "Регистрация компании"
        },
        "features": [
            {
                "title": "Метод анализа иерархий",
                "desc": "Математически обоснованный подход к сравнению критериев, исключающий субъективность.",
                "icon": "bi-diagram-3"
            },
            {
                "title": "Прозрачные KPI",
                "desc": "Сотрудники видят свою формулу успеха и понимают, как формируется их премия.",
                "icon": "bi-eye"
            },
            {
                "title": "Дашборды",
                "desc": "Визуализация результатов команды в реальном времени для принятия решений.",
                "icon": "bi-bar-chart"
            }
        ],
        "stats": [
            {"value": "1M+", "label": "Распределенных премий"},
            {"value": "500+", "label": "Активных сотрудников"},
            {"value": "98%", "label": "Точность оценки"}
        ],
        "footer": get_footer_data()
    }
    return render(request, 'evaluations/home.html', context=content)

@login_required
def employee_list(request):
    employees = User.objects.filter(
        company=request.user.company
    ).exclude(id=request.user.id)

    if request.user.role == 'manager':
        employees = employees.filter(role='employee')

    return render(request, 'evaluations/employee_list.html', {
        'employees': employees,
        'footer': get_footer_data()
    })

@login_required
def add_employee(request):
    # Только менеджер (или руководитель) может добавлять сотрудников
    if request.user.role not in ['head', 'manager']:
        return redirect('home')
    
    if request.method == 'POST':
        form = UserCreationFormExtended(request.POST, hide_position=False, company=request.user.company)
        if form.is_valid():
            user = form.save(commit=False)
            user.company = request.user.company
            user.role = 'employee'
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
            print("ПИСЬМО ДЛЯ СОТРУДНИКА:")
            print(message)
            print("="*50 + "\n")

            from django.conf import settings

            send_mail(
                subject, 
                message, 
                settings.DEFAULT_FROM_EMAIL, 
                [user.email], 
                fail_silently=False
            )
            return redirect('management_list')
    else:
        form = UserCreationFormExtended()
    
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
        'c_form': c_form, 'u_form': u_form, 'footer': get_footer_data()
    })

@login_required
def dashboard(request):
    if request.user.role in ['head', 'manager']:
        return redirect('management_list')
    
    criteria = EmployeeCriterion.objects.filter(employee=request.user)
    eval_result = EvaluationResult.objects.filter(employee=request.user).first()
    return render(request, 'evaluations/employee_dashboard.html', {
        'criteria': criteria,
        'eval_result': eval_result,
        'user': request.user
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
                fail_silently=False
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
    if request.user.role == 'head':
        users = User.objects.filter(company=request.user.company, role='manager')
        positions = Position.objects.filter(company=request.user.company).prefetch_related('base_criteria').order_by('name')

        if request.method == 'POST':
            if 'add_position' in request.POST or 'add_pos' in request.POST:
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
                criterion.delete()
                return redirect(reverse('management_list') + f'?opened_pos={criterion.position.id}')

        title = "Управление менеджерами и должностями"
        add_label = "Добавить менеджера"
        add_url = "add_manager"
    elif request.user.role == 'manager':
        users = User.objects.filter(company=request.user.company, role='employee')
        title = "Управление сотрудниками"
        add_label = "Добавить сотрудника"
        add_url = "add_employee"
    else:
        return redirect('dashboard')

    if request.method == 'POST' and request.user.role == 'head' and 'add_pos' in request.POST:
        pos_form = PositionForm(request.POST)
        if pos_form.is_valid():
            new_pos = pos_form.save(commit=False)
            new_pos.company = request.user.company
            new_pos.save()
            return redirect('management_list')
    else:
        pos_form = PositionForm()

    return render(request, 'evaluations/management_list.html', {
        'users_list': users,
        'positions': positions,
        'pos_form': pos_form,
        'title': title,
        'add_label': add_label,
        'add_url': add_url
    })

@login_required
def employee_list(request):
    if request.user.role != 'manager':
        return redirect('dashboard')

    employees = User.objects.filter(company=request.user.company, role='employee')
    
    page_data = {
        "title": "Управление командой",
        "description": "Здесь вы можете управлять профилями сотрудников и переходить к их оценке.",
        "summary_stats": {
            "total": employees.count(),
            "evaluated": 0,  
            "pending": employees.count()
        }
    }
    
    return render(request, 'evaluations/employee_list.html', {
        'employees': employees,
        'page_data': page_data,
        'footer': get_footer_data() 
    })

@login_required
def manage_criteria(request, employee_id):
    employee = get_object_or_404(User, id=employee_id, company=request.user.company)
    
    base_pos_criteria = PositionCriterion.objects.filter(position=employee.position)
    for bp_crit in base_pos_criteria:
        EmployeeCriterion.objects.get_or_create(
            employee=employee, 
            name=bp_crit.name,
            is_individual=False
        )
            
    error_message = None

    if request.method == 'POST':
        if 'add_individual' in request.POST:
            individual_count = EmployeeCriterion.objects.filter(employee=employee, is_individual=True).count()
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
                EmployeeCriterion, 
                id=crit_id, 
                employee=employee, 
                is_individual=True
            )
            criterion.delete()
            return redirect('manage_criteria', employee_id=employee.id)

    criteria = employee.assigned_criteria.all().order_by('is_individual', 'name')
    individual_count = EmployeeCriterion.objects.filter(employee=employee, is_individual=True).count()

    return render(request, 'evaluations/manage_criteria.html', {
        'employee': employee,
        'criteria': criteria,
        'error_message': error_message,
        'individual_count': individual_count
    })

def calculate_ahp_weights(matrix):
    matrix = np.array(matrix)
    eig_vals, eig_vecs = np.linalg.eig(matrix)
    max_eig_vec = eig_vecs[:, eig_vals.argmax()].real
    weights = max_eig_vec / max_eig_vec.sum()
    return weights.tolist()

@login_required
def compare_criteria(request, employee_id):
    employee = get_object_or_404(User, id=employee_id, company=request.user.company)
    criteria = list(employee.assigned_criteria.all())
    
    if len(criteria) < 2:
        return redirect('manage_criteria', employee_id=employee.id)

    pairs = list(itertools.combinations(criteria, 2))

    if request.method == 'POST':
        PairwiseComparison.objects.filter(employee=employee, evaluator=request.user).delete()
        
        for c1, c2 in pairs:
            val = float(request.POST.get(f'pair_{c1.id}_{c2.id}'))
            PairwiseComparison.objects.create(
                employee=employee,
                evaluator=request.user,
                criterion1=c1,
                criterion2=c2,
                value=val
            )

        if request.user.role in ['head', 'manager']:
            
            n = len(criteria)
            matrix = np.ones((n, n))
            criteria_ids = [c.id for c in criteria]
            
            comparisons = PairwiseComparison.objects.filter(employee=employee, evaluator=request.user)
            for comp in comparisons:
                idx1 = criteria_ids.index(comp.criterion1.id)
                idx2 = criteria_ids.index(comp.criterion2.id)
                matrix[idx1, idx2] = comp.value
                matrix[idx2, idx1] = 1 / comp.value

            weights = calculate_ahp_weights(matrix)
            for i, crit in enumerate(criteria):
                crit.weight = round(weights[i], 4)
                crit.manager_evaluated = True
                crit.save()
        else:
            for crit in criteria:
                crit.employee_evaluated = True
                crit.save()

        return redirect('dashboard' if request.user.role == 'employee' else 'management_list')

    return render(request, 'evaluations/compare_criteria.html', {
        'employee': employee,
        'pairs': pairs,
        'saaty_scale': [
            (1, 'Равнозначно'),
            (3, 'Умеренное превосходство'),
            (5, 'Сильное превосходство'),
            (7, 'Очень сильное'),
            (9, 'Абсолютное'),
        ]
    })
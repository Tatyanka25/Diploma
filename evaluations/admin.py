from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Company, Position, User, Criterion, EmployeePerformance, 
    EvaluationResult, PositionCriterion, EmployeeCriterion, 
    PairwiseComparison, CriterionScore, EvaluationPhase
)


class PositionCriterionInline(admin.TabularInline):
    model = PositionCriterion
    extra = 1

class EmployeeCriterionInline(admin.TabularInline):
    model = EmployeeCriterion
    extra = 0
    readonly_fields = ('weight', 'manager_evaluated', 'employee_evaluated')


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Настройка управления пользователями"""
    list_display = ('username', 'last_name', 'first_name', 'role', 'company', 'position', 'manager')
    list_filter = ('role', 'company', 'position')
    search_fields = ('username', 'last_name', 'email')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': (
            'role', 'company', 'position', 'patronymic', 
            'phone_number', 'birth_date', 'manager', 'criteria_confirmed'
        )}),
    )
    inlines = [EmployeeCriterionInline]

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'bonus_pool', 'weight_manager', 'weight_self', 'weight_peer')
    search_fields = ('name',)

@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'company')
    list_filter = ('company',)
    search_fields = ('name',)
    inlines = [PositionCriterionInline]

@admin.register(EmployeeCriterion)
class EmployeeCriterionAdmin(admin.ModelAdmin):
    list_display = ('name', 'employee', 'weight', 'is_individual', 'manager_evaluated', 'employee_evaluated')
    list_filter = ('is_individual', 'manager_evaluated', 'employee_evaluated', 'employee__company')
    search_fields = ('name', 'employee__last_name')

@admin.register(EvaluationResult)
class EvaluationResultAdmin(admin.ModelAdmin):
    list_display = ('employee', 'total_score', 'share', 'updated_at')
    readonly_fields = ('updated_at',)
    ordering = ('-total_score',)

@admin.register(CriterionScore)
class CriterionScoreAdmin(admin.ModelAdmin):
    list_display = ('get_employee', 'criterion', 'evaluator', 'score')
    list_filter = ('score', 'evaluator__role')
    
    def get_employee(self, obj):
        return obj.criterion.employee
    get_employee.short_description = 'Кого оценивают'

@admin.register(EvaluationPhase)
class EvaluationPhaseAdmin(admin.ModelAdmin):
    list_display = ('position', 'manager', 'is_active', 'created_at')
    list_filter = ('is_active', 'position__company')

@admin.register(PairwiseComparison)
class PairwiseComparisonAdmin(admin.ModelAdmin):
    list_display = ('employee', 'evaluator', 'criterion1', 'criterion2', 'value')

admin.site.register(PositionCriterion)
admin.site.register(Criterion)
admin.site.register(EmployeePerformance)
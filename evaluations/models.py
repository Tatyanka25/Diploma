from django.contrib.auth.models import AbstractUser
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название компании")
    bonus_pool = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0, 
        verbose_name="Премиальный фонд"
    )
    weight_manager = models.FloatField(default=0.6, verbose_name="Вес оценки менеджера")
    weight_self = models.FloatField(default=0.2, verbose_name="Вес самооценки")
    weight_peer = models.FloatField(default=0.2, verbose_name="Вес оценки коллег")

    def __str__(self):
        return self.name
    
class Position(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='positions')
    name = models.CharField(max_length=100, verbose_name="Название должности")

    def __str__(self):
        return self.name

class User(AbstractUser):
    ROLE_CHOICES = (
        ('head', 'Руководитель компании'), 
        ('manager', 'Менеджер'),            
        ('employee', 'Сотрудник'),          
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='employee')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True, related_name='users')
    position = models.ForeignKey(
        Position, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="Должность"
    )
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="Номер телефона")
    patronymic = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    criteria_confirmed = models.BooleanField(default=False, verbose_name="Критерии подтверждены менеджером")
    manager = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='subordinates',
        verbose_name="Руководитель"
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})" 

class Criterion(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    
    def __str__(self):
        return self.name

class EmployeePerformance(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='performances')
    criterion = models.ForeignKey(Criterion, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0, verbose_name="Оценка (0-10)") 
    
    class Meta:
        unique_together = ('employee', 'criterion')

class EvaluationResult(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='evaluation_results')
    total_score = models.FloatField(default=0.0, verbose_name="Итоговый балл")
    share = models.FloatField(default=0.0, verbose_name="Доля в фонде (0.0 - 1.0)") 
    updated_at = models.DateTimeField(auto_now=True)
    month = models.PositiveSmallIntegerField(verbose_name="Месяц")
    year = models.PositiveSmallIntegerField(verbose_name="Год")
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    def share_percentage(self):
        return f"{self.share * 100:.2f}%"
    
    class Meta:
        ordering = ['-total_score']

    def __str__(self):
        return f"{self.employee.username} - {self.month}/{self.year} (Создано: {self.created_at})"
    
class PositionCriterion(models.Model):
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='base_criteria')
    name = models.CharField(max_length=100, verbose_name="Название критерия")

    def __str__(self):
        return f"{self.name} ({self.position.name})"
    
class EmployeeCriterion(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assigned_criteria')
    name = models.CharField(max_length=100)
    weight = models.FloatField(default=0.0)
    manager_evaluated = models.BooleanField(default=False)
    employee_evaluated = models.BooleanField(default=False)

    is_individual = models.BooleanField(default=False)

    manager_evaluated = models.BooleanField(default=False)
    employee_evaluated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.employee.username}"
    
class PairwiseComparison(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comparisons')
    evaluator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_evaluations')
    criterion1 = models.ForeignKey(EmployeeCriterion, on_delete=models.CASCADE, related_name='c1')
    criterion2 = models.ForeignKey(EmployeeCriterion, on_delete=models.CASCADE, related_name='c2')
    value = models.FloatField()

class CriterionScore(models.Model):
    criterion = models.ForeignKey(EmployeeCriterion, on_delete=models.CASCADE, related_name='scores')
    evaluator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_scores')
    score = models.PositiveSmallIntegerField(verbose_name="Оценка (1-10)")
    is_archived = models.BooleanField(default=False, verbose_name="В архиве") # Добавить это
    created_at = models.DateTimeField(auto_now_add=True)


class EvaluationPhase(models.Model):
    manager = models.ForeignKey(User, on_delete=models.CASCADE, related_name='launched_phases')
    position = models.ForeignKey(Position, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    def __str__(self):
        return f"Оценка {self.position.name} (Рук: {self.manager.username})"
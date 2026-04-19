from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import RussianSetPasswordForm

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='evaluations/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('register/', views.register_company, name='register_company'),
    path('employees/<int:employee_id>/criteria/', views.manage_criteria, name='manage_criteria'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('management/', views.management_list, name='management_list'),
    path('management/add-manager/', views.add_manager, name='add_manager'),
    path('management/add-employee/', views.add_employee, name='add_employee'),
    path('set-password/<uidb64>/<token>/', 
     auth_views.PasswordResetConfirmView.as_view(
         template_name='evaluations/password_set_form.html',
         form_class=RussianSetPasswordForm, 
         success_url='/password-set-complete/'
     ), 
     name='password_set_confirm'),
         
    path('password-set-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='evaluations/password_set_complete.html'
         ), 
         name='password_set_complete'),
    path('compare-criteria/<int:employee_id>/', views.compare_criteria, name='compare_criteria'),
    path('trigger-reset/', views.trigger_password_reset, name='trigger_password_reset'),
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='evaluations/password_set_form.html', 
             success_url='/password-set-complete/'
         ), name='password_reset_confirm'),
    path('rate/<int:employee_id>/', views.rate_employee, name='rate_employee'),
    path('ratings/', views.ratings_view, name='ratings'),
    path('ratings/export/', views.export_ratings_excel, name='export_ratings'),
    path('ratings/start-new/', views.start_new_evaluation, name='start_new_evaluation'),
    path('employees/delete/<int:employee_id>/', views.delete_employee, name='delete_employee'),
    path('managers/delete/<int:manager_id>/', views.delete_manager, name='delete_manager'),
]
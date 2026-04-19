from django import forms
from .models import User, Company, Position
from django.contrib.auth.forms import SetPasswordForm
import re
from django.core.exceptions import ValidationError

class ReassignSubordinatesForm(forms.Form):
    new_manager = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Выберите нового руководителя для команды",
        widget=forms.Select(attrs={'class': 'form-select rounded-pill'})
    )

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company')
        exclude_user = kwargs.pop('exclude_user')
        super().__init__(*args, **kwargs)
        self.fields['new_manager'].queryset = User.objects.filter(
            company=company, 
            role__in=['manager', 'head']
        ).exclude(id=exclude_user.id)

class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ['name']
        labels = {'name': 'Название новой должности'}
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Ведущий аналитик'})
        }
    
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            return name.strip().capitalize()
        return name

class CompanyRegistrationForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name'] 
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название вашей компании'}),
        }
        labels = {
            'name': 'Название компании', 
        }

class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'username': 'Логин',
            'email': 'Email',
            'password': 'Пароль',
        }

class EmployeeCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Пароль")

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'position', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"]) 
        user.role = 'employee'
        if commit:
            user.save()
        return user
    
class UserCreationFormExtended(forms.ModelForm):
    birth_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label="Дата рождения"
    )
    
    patronymic = forms.CharField(max_length=100, required=False, label="Отчество", 
                                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'При наличии'}))

    class Meta:
        model = User
        fields = ['username', 'last_name', 'first_name', 'patronymic', 'email', 'phone_number', 'birth_date', 'position']
        labels = {
            'username': 'Логин',
            'last_name': 'Фамилия',
            'first_name': 'Имя',
            'email': 'Электронная почта',
            'phone_number': 'Номер телефона',
            'position': 'Должность',
        }

    def __init__(self, *args, **kwargs):
        self.hide_position = kwargs.pop('hide_position', False)
        self.user_company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        if self.user_company:
            self.fields['position'] = forms.ModelChoiceField(
            queryset=Position.objects.filter(company=self.user_company),
            empty_label="Выберите должность из списка",
            label="Должность",
            required=True,
            widget=forms.Select(attrs={'class': 'form-select'})
        )
        
        placeholders = {
        'username': 'ivanov_i',
        'last_name': 'Иванов',
        'first_name': 'Иван',
        'patronymic': 'Иванович',
        'email': 'example@mail.ru',
        'phone_number': '+79001234567',
        'birth_date': 'ДД.ММ.ГГГГ',
        }

        for field_name, field in self.fields.items():
            if field_name != 'position': 
                field.widget.attrs.update({
                'class': 'form-control',
                'placeholder': placeholders.get(field_name, '')
            })
            field.required = True
            
        if self.hide_position:
           self.fields['position'].required = False
           self.fields['position'].widget = forms.HiddenInput()
           self.fields['position'].label = ""
    
    def clean_cyrillic_name(self, value, field_label):
        if value:
            value = value.strip()
            if not re.match(r'^[а-яА-ЯёЁ\s-]+$', value):
                raise ValidationError(f"Поле '{field_label}' должно содержать только русские буквы.")
            return value.title()
        return value

    def clean_first_name(self):
        return self.clean_cyrillic_name(self.cleaned_data.get('first_name'), "Имя")

    def clean_last_name(self):
        return self.clean_cyrillic_name(self.cleaned_data.get('last_name'), "Фамилия")

    def clean_patronymic(self):
        return self.clean_cyrillic_name(self.cleaned_data.get('patronymic'), "Отчество")

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if not re.match(r'^\+?7\d{10}$|^8\d{10}$', phone):
            raise ValidationError("Введите корректный номер телефона (например, +79001234567)")
        return phone

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Пользователь с такой почтой уже зарегистрирован")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user
    
    def clean_birth_date(self):
        birth_date = self.cleaned_data.get('birth_date')
        from datetime import date
        if birth_date:
            if birth_date > date.today():
                raise ValidationError("Дата рождения не может быть в будущем.")
            if birth_date.year < 1920:
                raise ValidationError("Введите корректную дату рождения.")
        return birth_date

class RussianSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = "Новый пароль"
        self.fields['new_password1'].help_text = "Пароль должен быть не менее 8 символов."
        self.fields['new_password2'].label = "Повторите новый пароль"

class CompanyWeightsForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['weight_manager', 'weight_self', 'weight_peer']
        labels = {
            'weight_manager': 'Вес оценки менеджера (%)',
            'weight_self': 'Вес самооценки (%)',
            'weight_peer': 'Вес оценки коллег (%)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['weight_manager'] = int(self.instance.weight_manager * 100)
            self.initial['weight_self'] = int(self.instance.weight_self * 100)
            self.initial['weight_peer'] = int(self.instance.weight_peer * 100)

    def clean(self):
        cleaned_data = super().clean()
        w_m = cleaned_data.get('weight_manager')
        w_s = cleaned_data.get('weight_self')
        w_p = cleaned_data.get('weight_peer')

        if w_m is not None and w_s is not None and w_p is not None:
            if w_m + w_s + w_p != 100:
                raise forms.ValidationError("Сумма всех весов должна быть строго равна 100%")
        
        return cleaned_data
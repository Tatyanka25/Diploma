import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

username = 'admin1'
email = 'lapshinatatyana25@mail.ru'
password = '12345678'

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username=username, 
        email=email, 
        password=password,
        role='head'
    )
    print(f"Администратор {username} создан!")
else:
    print("Администратор уже существует.")
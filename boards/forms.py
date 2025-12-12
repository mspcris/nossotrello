from django import forms
from .models import Column, Card, Board

class ColumnForm(forms.ModelForm):
    class Meta:
        model = Column
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "border p-2 rounded w-full",
                "placeholder": "Nome da coluna"
            })
        }

class CardForm(forms.ModelForm):
    class Meta:
        model = Card
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "border p-2 rounded w-full",
                "placeholder": "Título do card"
            })
        }

class BoardForm(forms.ModelForm):
    class Meta:
        model = Board
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "border p-2 rounded w-full",
                "placeholder": "Nome do quadro"
            })
        }

from .models import Board

class BoardForm(forms.ModelForm):
    class Meta:
        model = Board
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Nome do quadro"})
        }

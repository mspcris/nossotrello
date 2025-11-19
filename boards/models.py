from django.db import models

class Board(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Column(models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class Meta:
    ordering = ["position"]

    def __str__(self):
        return f"{self.board.name} - {self.name}"


class Card(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    tags = models.CharField(max_length=255, blank=True, null=True)
    attachment = models.FileField(upload_to="attachments/", blank=True, null=True)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)


    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.title
    



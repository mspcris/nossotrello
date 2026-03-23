"""
Management command to merge one user into another.

Usage:
    python manage.py merge_users <source_email> <target_email> [--dry-run] [--delete-source]

Example:
    python manage.py merge_users robson@mrfsolution.com.br robson.fernandes@mrfsolution.com.br --delete-source
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = "Merge all data from source user into target user, then optionally delete source."

    def add_arguments(self, parser):
        parser.add_argument("source_email", type=str, help="Email of the user to merge FROM (will be deleted)")
        parser.add_argument("target_email", type=str, help="Email of the user to merge INTO (will be kept)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
        parser.add_argument("--delete-source", action="store_true", help="Delete the source user after merging")

    def handle(self, *args, **options):
        source_email = options["source_email"]
        target_email = options["target_email"]
        dry_run = options["dry_run"]
        delete_source = options["delete_source"]

        source_user = self._get_user(source_email)
        target_user = self._get_user(target_email)

        self.stdout.write(f"Source: {source_user.email} (id={source_user.id}, username={source_user.username})")
        self.stdout.write(f"Target: {target_user.email} (id={target_user.id}, username={target_user.username})")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No changes will be made.\n"))

        with transaction.atomic():
            self._merge(source_user, target_user, dry_run)

            if delete_source and not dry_run:
                source_user.delete()
                self.stdout.write(self.style.SUCCESS(f"\nSource user {source_email} deleted."))
            elif delete_source and dry_run:
                self.stdout.write(self.style.WARNING(f"\n[DRY RUN] Would delete source user {source_email}."))

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("\nDone."))

    def _get_user(self, identifier):
        from django.db.models import Q
        try:
            return User.objects.get(Q(email=identifier) | Q(username=identifier))
        except User.DoesNotExist:
            raise CommandError(f"User not found: {identifier}")
        except User.MultipleObjectsReturned:
            raise CommandError(f"Multiple users found for: {identifier} — use a more specific identifier")

    def _merge(self, source, target, dry_run):
        from boards.models import (
            Organization,
            OrganizationMembership,
            Board,
            BoardMembership,
            BoardGroup,
            BoardActivityReadState,
            BoardAccessRequest,
            Card,
            CardLog,
            CardSeen,
            CardNotificationLog,
            CardFollow,
            Mention,
            ColumnFollow,
            UserProfile,
            UserBoardPreference,
        )

        try:
            from boards.models import SocialPost, SocialPostSeen
            has_social = True
        except ImportError:
            has_social = False

        try:
            from tracktime.models import Project, ActivityType, Team, TimeEntry, TrackPresence
            has_tracktime = True
        except ImportError:
            has_tracktime = False

        # ------------------------------------------------------------------ #
        # Simple FK fields (just reassign user)
        # ------------------------------------------------------------------ #

        simple_fk = [
            # (Model, field_name, description)
            (Organization, "owner", "Organizations owned"),
            (Board, "created_by", "Boards created_by"),
            (Card, "created_by", "Cards created_by"),
            (Card, "delivered_by", "Cards delivered_by"),
            (CardLog, "actor", "CardLog actor"),
            (Mention, "actor", "Mention actor (mentions_made)"),
        ]

        for Model, field, desc in simple_fk:
            qs = Model.objects.filter(**{field: source})
            count = qs.count()
            if count:
                self.stdout.write(f"  {desc}: {count} records")
                if not dry_run:
                    qs.update(**{field: target})

        # ------------------------------------------------------------------ #
        # FKs with unique_together — need conflict handling
        # ------------------------------------------------------------------ #

        # OrganizationMembership: unique (organization, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=OrganizationMembership,
            user_field="user",
            unique_field="organization",
            desc="OrganizationMembership",
        )

        # BoardMembership: unique (board, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=BoardMembership,
            user_field="user",
            unique_field="board",
            desc="BoardMembership",
        )

        # BoardActivityReadState: unique (board, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=BoardActivityReadState,
            user_field="user",
            unique_field="board",
            desc="BoardActivityReadState",
        )

        # BoardAccessRequest: unique (board, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=BoardAccessRequest,
            user_field="user",
            unique_field="board",
            desc="BoardAccessRequest",
        )

        # CardSeen: unique (card, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=CardSeen,
            user_field="user",
            unique_field="card",
            desc="CardSeen",
        )

        # CardFollow: unique (card, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=CardFollow,
            user_field="user",
            unique_field="card",
            desc="CardFollow",
        )

        # Mention mentioned_user: unique (card, mentioned_user, source)
        self._transfer_mention_received(source, target, dry_run)

        # ColumnFollow: unique (column, user)
        self._transfer_with_unique(
            source, target, dry_run,
            model=ColumnFollow,
            user_field="user",
            unique_field="column",
            desc="ColumnFollow",
        )

        # CardNotificationLog: unique (card, user, kind, run_date)
        # Transfer those where target doesn't already have the same combo
        self._transfer_card_notification_log(source, target, dry_run)

        # BoardGroup: no strict unique, just reassign
        qs = BoardGroup.objects.filter(user=source)
        count = qs.count()
        if count:
            self.stdout.write(f"  BoardGroup: {count} records")
            if not dry_run:
                qs.update(user=target)

        # ------------------------------------------------------------------ #
        # Social
        # ------------------------------------------------------------------ #
        if has_social:
            qs = SocialPost.objects.filter(user=source)
            count = qs.count()
            if count:
                self.stdout.write(f"  SocialPost: {count} records")
                if not dry_run:
                    qs.update(user=target)

            # SocialPostSeen: unique (viewer, target_user)
            self._transfer_with_unique(
                source, target, dry_run,
                model=SocialPostSeen,
                user_field="viewer",
                unique_field="target_user",
                desc="SocialPostSeen (as viewer)",
            )
            self._transfer_with_unique(
                source, target, dry_run,
                model=SocialPostSeen,
                user_field="target_user",
                unique_field="viewer",
                desc="SocialPostSeen (as target_user)",
            )

        # ------------------------------------------------------------------ #
        # Tracktime
        # ------------------------------------------------------------------ #
        if has_tracktime:
            for Model, field, desc in [
                (Project, "created_by", "Tracktime Project created_by"),
                (ActivityType, "created_by", "Tracktime ActivityType created_by"),
                (TimeEntry, "user", "Tracktime TimeEntry"),
            ]:
                qs = Model.objects.filter(**{field: source})
                count = qs.count()
                if count:
                    self.stdout.write(f"  {desc}: {count} records")
                    if not dry_run:
                        qs.update(**{field: target})

            # Team M2M
            teams = Team.objects.filter(members=source)
            for team in teams:
                self.stdout.write(f"  Team M2M: team id={team.id}")
                if not dry_run:
                    if not team.members.filter(pk=target.pk).exists():
                        team.members.add(target)
                    team.members.remove(source)

            # TrackPresence (OneToOne)
            try:
                tp = TrackPresence.objects.get(user=source)
                self.stdout.write(f"  TrackPresence: source has one")
                if not dry_run:
                    if not TrackPresence.objects.filter(user=target).exists():
                        tp.user = target
                        tp.save()
                    else:
                        self.stdout.write(self.style.WARNING("    Target already has TrackPresence — skipping (keeping target's)"))
                        tp.delete()
            except TrackPresence.DoesNotExist:
                pass

        # ------------------------------------------------------------------ #
        # OneToOne: UserProfile
        # ------------------------------------------------------------------ #
        try:
            src_profile = UserProfile.objects.get(user=source)
            self.stdout.write(f"  UserProfile: source has one (handle='{src_profile.handle}')")
            if not dry_run:
                if not UserProfile.objects.filter(user=target).exists():
                    src_profile.user = target
                    src_profile.save()
                else:
                    self.stdout.write(self.style.WARNING("    Target already has UserProfile — skipping (keeping target's, deleting source's)"))
                    src_profile.delete()
        except UserProfile.DoesNotExist:
            pass

        # ------------------------------------------------------------------ #
        # OneToOne: UserBoardPreference
        # ------------------------------------------------------------------ #
        try:
            src_pref = UserBoardPreference.objects.get(user=source)
            self.stdout.write(f"  UserBoardPreference: source has one")
            if not dry_run:
                if not UserBoardPreference.objects.filter(user=target).exists():
                    src_pref.user = target
                    src_pref.save()
                else:
                    self.stdout.write(self.style.WARNING("    Target already has UserBoardPreference — skipping (keeping target's, deleting source's)"))
                    src_pref.delete()
        except UserBoardPreference.DoesNotExist:
            pass

    # ---------------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------------- #

    def _transfer_with_unique(self, source, target, dry_run, model, user_field, unique_field, desc):
        """
        Transfer records from source to target handling unique_together (user_field, unique_field).
        Records where target already has a conflicting row are deleted from source.
        """
        qs = model.objects.filter(**{user_field: source})
        total = qs.count()
        if not total:
            return

        transferred = 0
        skipped = 0

        for obj in qs:
            conflict_value = getattr(obj, unique_field + "_id", None) or getattr(obj, unique_field)
            conflict_filter = {user_field: target, unique_field: conflict_value}
            if model.objects.filter(**conflict_filter).exists():
                skipped += 1
                if not dry_run:
                    obj.delete()
            else:
                transferred += 1
                if not dry_run:
                    setattr(obj, user_field, target)
                    obj.save()

        self.stdout.write(
            f"  {desc}: {total} total — {transferred} transferred, {skipped} skipped (conflict with target)"
        )

    def _transfer_mention_received(self, source, target, dry_run):
        from boards.models import Mention
        qs = Mention.objects.filter(mentioned_user=source)
        total = qs.count()
        if not total:
            return

        transferred = 0
        skipped = 0

        for obj in qs:
            if Mention.objects.filter(card=obj.card, mentioned_user=target, source=obj.source).exists():
                skipped += 1
                if not dry_run:
                    obj.delete()
            else:
                transferred += 1
                if not dry_run:
                    obj.mentioned_user = target
                    obj.save()

        self.stdout.write(
            f"  Mention (mentioned_user): {total} total — {transferred} transferred, {skipped} skipped"
        )

    def _transfer_card_notification_log(self, source, target, dry_run):
        from boards.models import CardNotificationLog
        qs = CardNotificationLog.objects.filter(user=source)
        total = qs.count()
        if not total:
            return

        transferred = 0
        skipped = 0

        for obj in qs:
            if CardNotificationLog.objects.filter(
                card=obj.card, user=target, kind=obj.kind, run_date=obj.run_date
            ).exists():
                skipped += 1
                if not dry_run:
                    obj.delete()
            else:
                transferred += 1
                if not dry_run:
                    obj.user = target
                    obj.save()

        self.stdout.write(
            f"  CardNotificationLog: {total} total — {transferred} transferred, {skipped} skipped"
        )

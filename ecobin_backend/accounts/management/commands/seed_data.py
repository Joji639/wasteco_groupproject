import os
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from accounts.models import UserProfile, OperatorProfile, OperatorAdminProfile
from accounts.managers import ROLE_TO_GROUP
from pickups.models import PickupRequest, OperatorReview
from complaints.models import Complaint, ComplaintStatusHistory
from payments.models import WasteCollection, Payment
from chat.models import Community, CommunityMember, Message

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed the database with demo data'

    def handle(self, *args, **options):
        if User.objects.count() > 5:
            self.stdout.write('Already seeded, skipping')
            return

        users_data = [
            ("ecobinadmin@gmail.com", "9000000001", "ecobin@2026!", "superadmin", True, True, None, None),
            ("jacob@gmail.com", "9000000002", "Test123!", "operatoradmin", False, False, None, "TVM"),
            ("vaxax48200@slotbeer.com", "9000000003", "Test123!", "operatoradmin", False, False, None, "Kazhakkoottam"),
            ("rahul@test.com", "9000000004", "Test123!", "operator", False, False, "1", None),
            ("suresh@test.com", "9000000005", "Test123!", "operator", False, False, "2", None),
            ("vishnu@test.com", "9000000006", "Test123!", "operator", False, False, "3", None),
            ("akhil@test.com", "9000000007", "Test123!", "operator", False, False, "4", None),
            ("operator2@example.com", "9000000008", "Test123!", "operator", False, False, "5", None),
            ("sulfi@gmail.com", "9000000009", "Test123!", "operator", False, False, "6", None),
            ("akhil@gmil.com", "9000000010", "Test123!", "operator", False, False, "7", None),
            ("user1@test.com", "9000000011", "Test123!", "user", False, False, None, None),
            ("user2@test.com", "9000000012", "Test123!", "user", False, False, None, None),
            ("jojij@gmail.com", "9000000013", "Test123!", "user", False, False, None, None),
        ]

        for email, phone, pw, role, su, st, ward, pan in users_data:
            if User.objects.filter(email=email).exists():
                self.stdout.write(f'SKIP {email}')
                continue
            u = User.objects.create_user(base_role=role, is_superuser=su, is_staff=st, email=email, phone=phone)
            u.set_password(pw)
            u.save()
            if role in ROLE_TO_GROUP:
                g, _ = Group.objects.get_or_create(name=ROLE_TO_GROUP[role])
                g.user_set.add(u)
            if role == "user":
                UserProfile.objects.create(user=u)
            elif role == "operator":
                OperatorProfile.objects.create(user=u, ward_no=ward, is_verified=True)
            elif role == "operatoradmin":
                OperatorAdminProfile.objects.create(user=u, panchayath=pan, is_verified=True)
            self.stdout.write(self.style.SUCCESS(f'CREATED {email} ({role})'))

        sa = User.objects.get(email="ecobinadmin@gmail.com")
        oa1 = User.objects.get(email="jacob@gmail.com")
        oa2 = User.objects.get(email="vaxax48200@slotbeer.com")
        ops = list(User.objects.filter(base_role="operator"))
        users = list(User.objects.filter(base_role="user"))

        places = [
            ("MG Road, Thiruvananthapuram", 8.5241, 76.9366),
            ("Kazhakkoottam Junction", 8.5478, 76.8682),
            ("Vattiyoorkavu", 8.5074, 76.9577),
            ("Kowdiar", 8.5180, 76.9560),
            ("Sreekaryam", 8.5530, 76.9050),
            ("Pattom", 8.5290, 76.9340),
            ("Neyyattinkara", 8.3988, 77.0868),
            ("Attingal", 8.6890, 76.8820),
            ("Varkala Beach Road", 8.7333, 76.7167),
            ("Kovalam", 8.4004, 76.9787),
        ]

        pickup_data = [
            (0, "ON_DEMAND", 0, "COMPLETED", "Mixed household waste", 0, oa1),
            (0, "ON_DEMAND", 1, "COLLECTED", "Plastic bottles and cardboard", 1, oa1),
            (0, "SCHEDULED", 2, "ASSIGNED", "Electronic waste", 2, oa2),
            (1, "ON_DEMAND", 3, "PENDING", "Kitchen waste", None, None),
            (1, "SCHEDULED", 4, "ACCEPTED", "Monthly scheduled pickup", 3, oa1),
            (1, "ON_DEMAND", 5, "ON_THE_WAY", "Large items", 0, oa2),
            (2, "ON_DEMAND", 6, "COMPLETED", "Construction debris", 4, oa1),
            (2, "SCHEDULED", 7, "COMPLETED", "Regular weekly waste", 5, oa2),
            (2, "ON_DEMAND", 8, "REJECTED", "Hazardous chemicals", None, oa1),
        ]

        pickups = []
        for i, (u_idx, ptype, pl_idx, status, desc, op_idx, oa) in enumerate(pickup_data):
            place, lat, lng = places[pl_idx]
            p = PickupRequest(
                user=users[u_idx], pickup_type=ptype, place=place,
                latitude=Decimal(str(lat)), longitude=Decimal(str(lng)),
                description=desc, status=status,
            )
            if status not in ("PENDING", "REJECTED") and oa:
                p.accepted_by = oa
            if status == "REJECTED":
                p.rejected_by = oa
                p.rejection_reason = "Cannot handle hazardous waste"
            if op_idx is not None and status not in ("PENDING", "REJECTED"):
                p.assigned_operator = ops[op_idx]
                p.assigned_by = oa
            p.save()
            pickups.append(p)

        for pickup in pickups:
            if pickup.status == "COMPLETED" and pickup.assigned_operator:
                OperatorReview.objects.create(
                    pickup_request=pickup, user=pickup.user,
                    operator=pickup.assigned_operator, rating=4,
                    comment="Good service"
                )

        complaint_data = [
            (0, 0, "PENDING", "Waste not collected on scheduled day"),
            (0, 3, "ASSIGNED", "Operator was rude"),
            (1, 4, "IN_PROGRESS", "Smell from uncollected waste"),
            (1, 1, "RESOLVED", "Issue resolved quickly"),
        ]
        for u_idx, pl_idx, status, desc in complaint_data:
            place, lat, lng = places[pl_idx]
            c = Complaint(
                user=users[u_idx], place=place,
                latitude=Decimal(str(lat)), longitude=Decimal(str(lng)),
                description=desc, status=status,
            )
            if status in ("ASSIGNED", "IN_PROGRESS", "RESOLVED"):
                c.assigned_operator = ops[0]
            c.save()
            ComplaintStatusHistory.objects.create(complaint=c, status="PENDING", changed_by=users[u_idx])
            if status != "PENDING":
                ComplaintStatusHistory.objects.create(complaint=c, status=status, changed_by=oa1)

        for i, pickup in enumerate(pickups):
            if pickup.status in ("COMPLETED", "COLLECTED") and pickup.assigned_operator:
                wc = WasteCollection.objects.create(
                    pickup_request=pickup, operator=pickup.assigned_operator,
                    plastic_kg=Decimal("5.50"), e_waste_kg=Decimal("2.00"),
                    payment_method="CASH", status="PAID",
                )
                Payment.objects.create(
                    collection=wc, amount=wc.total_amount,
                    payment_method="CASH", payment_status="CAPTURED",
                )

        all_staff = [oa1, oa2] + ops
        c1 = Community.objects.create(name="TVM West Ward Operators", description="Discussion group", created_by=oa1)
        c2 = Community.objects.create(name="EcoBin General", description="General updates", created_by=oa2)
        for c in [c1, c2]:
            for staff in all_staff:
                CommunityMember.objects.create(
                    community=c, user=staff, added_by=oa1,
                    is_group_admin=(staff == oa1),
                )
            Message.objects.create(community=c, sender=oa1, content="Welcome to the group!")
            Message.objects.create(community=c, sender=ops[0], content="Morning pickup done!")

        self.stdout.write(self.style.SUCCESS(f'DONE: {User.objects.count()} users, {PickupRequest.objects.count()} pickups, {Complaint.objects.count()} complaints'))

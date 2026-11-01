"""DEVELOPMENT-ONLY demo data (donors, NGOs, listings).

There is deliberately NO default admin account anywhere: create one with
    flask --app app create-admin
"""
from datetime import timedelta

from .core import db
from .models import (CLAIMED, DONOR, NGO, PENDING, PICKED_UP, DonationListing,
                     User, utcnow)

DEMO_PASSWORD = "demo1234"  # demo users only; never used for admins


def seed_demo():
    """Only runs when the database has no donors/NGOs yet."""
    if User.query.filter(User.role.in_([DONOR, NGO])).first():
        return

    people = [
        ("Spice Garden Restaurant", DONOR, "donor1@demo.local", 12.9784, 77.6408, "12 Church Street, Indiranagar"),
        ("Sunrise Bakery", DONOR, "donor2@demo.local", 12.9352, 77.6245, "44 80 Feet Road, Koramangala"),
        ("Green Leaf Caterers", DONOR, "donor3@demo.local", 12.9757, 77.6011, "7 MG Road"),
        ("Jayanagar Community Hall", DONOR, "donor4@demo.local", 12.9250, 77.5938, "21 4th Block, Jayanagar"),
        ("Hope Foundation", NGO, "ngo1@demo.local", 12.9611, 77.6387, None),
        ("Meals For All", NGO, "ngo2@demo.local", 12.9141, 77.6101, None),
    ]
    users = {}
    for name, role, email, lat, lng, address in people:
        user = User(name=name, role=role, email=email, latitude=lat,
                    longitude=lng, address=address,is_approved=True)
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        users[email] = user
    db.session.flush()

    now = utcnow()
    rows = [
        # donor, food, qty, expiry hours, minutes ago, status, claimed by
        ("donor1@demo.local", "Veg biryani & raita", "40 meals", 6, 20, PENDING, None),
        ("donor1@demo.local", "Chapati & dal tadka", "25 meals", 4, 45, PENDING, None),
        ("donor2@demo.local", "Fresh bread loaves & buns", "30 pieces", 10, 60, PENDING, None),
        ("donor3@demo.local", "Mixed fruit platters", "12 kg", 8, 30, PENDING, None),
        ("donor4@demo.local", "Wedding lunch surplus (rice, curry)", "80 meals", 5, 15, PENDING, None),
        ("donor2@demo.local", "Sandwiches & muffins", "50 pieces", 6, 180, CLAIMED, "ngo1@demo.local"),
        ("donor3@demo.local", "Idli, sambar & chutney", "60 meals", 5, 400, PICKED_UP, "ngo2@demo.local"),
    ]
    for donor, food, qty, hours, ago, status, ngo in rows:
        db.session.add(DonationListing(
            donor_id=users[donor].id, food_type=food, quantity=qty,
            expiry_window=hours, status=status,
            claimed_by_ngo_id=users[ngo].id if ngo else None,
            created_at=now - timedelta(minutes=ago)))
    db.session.commit()

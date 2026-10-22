"""PR-03 Synthetic people: names, birth dates and numbers drawn from a seeded generator, so a seed always gives the same
people and nobody real is ever described. Phone numbers start with 0 (never a dialable Indian mobile; the enquiry
acknowledgement also skips them); e-mail addresses use the profile's example domain (example.edu is not an IANA-reserved name; nothing is ever sent to it)."""

import hashlib
import random

FEMALE = [
	"Aarthi", "Abirami", "Anitha", "Bhavani", "Deepika", "Divya", "Gayathri", "Harini", "Indhu", "Janani", "Kavya", "Lakshmi",
	"Meena", "Nandhini", "Priya", "Rakshana", "Sangeetha", "Shalini", "Swetha", "Thamarai", "Uma", "Varsha", "Yamini", "Keerthana",
]  # fmt: skip
MALE = [
	"Arjun", "Aravind", "Balaji", "Charan", "Dinesh", "Ganesh", "Hari", "Ilango", "Jeevan", "Karthik", "Logesh", "Manoj",
	"Naveen", "Prakash", "Rahul", "Sanjay", "Surya", "Tamilselvan", "Vignesh", "Yogesh", "Ashwin", "Bharath", "Gokul", "Kishore",
]  # fmt: skip
SURNAMES = [
	"Subramanian", "Raman", "Krishnan", "Murugan", "Selvam", "Pandian", "Natarajan", "Venkatesh", "Ramesh", "Anand", "Chandran",
	"Devi", "Kumar", "Lakshmanan", "Mohan", "Narayanan", "Palani", "Rajan", "Sekar", "Thangaraj", "Velu", "Annamalai",
]  # fmt: skip


class Person:
	"""One generated person; `key` is its stable identity, e.g. "applicant-cse-03"."""

	def __init__(self, seed, key, youngest_year, oldest_year, domain):
		rng = random.Random(f"{seed}:{key}")
		self.key = key
		self.gender = rng.choice(["Female", "Male"])
		self.first_name = rng.choice(FEMALE if self.gender == "Female" else MALE)
		self.last_name = rng.choice(SURNAMES)
		self.date_of_birth = f"{rng.randint(oldest_year, youngest_year)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
		self.email = f"{key}@{domain}"
		digest = hashlib.sha1(f"{seed}:{key}".encode()).hexdigest()
		self.mobile = f"0000{int(digest[:8], 16) % 1000000:06d}"  # starts with 0: never a real Indian mobile number

	@property
	def full_name(self):
		return f"{self.first_name} {self.last_name}"


class People:
	"""Hands out distinct people: a second person with the same name and birth date would be a duplicate candidate."""

	def __init__(self, seed, domain):
		self.seed, self.domain = seed, domain
		self.taken, self.mobiles, self.made = set(), set(), {}

	def make(self, key, youngest_year, oldest_year):
		"""The person of `key`; asking again for a key returns the same person."""
		if key in self.made:
			return self.made[key]
		person = Person(self.seed, key, youngest_year, oldest_year, self.domain)
		attempt = 0
		while (person.full_name, person.date_of_birth) in self.taken or person.mobile in self.mobiles:
			attempt += 1
			person = Person(self.seed, f"{key}~{attempt}", youngest_year, oldest_year, self.domain)
			person.key, person.email = key, f"{key}@{self.domain}"
		self.taken.add((person.full_name, person.date_of_birth))
		self.mobiles.add(person.mobile)
		self.made[key] = person
		return person

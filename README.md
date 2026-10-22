# Smart Campus Resource Booking System (single file)

Everything is in ONE file: `smart_campus.py`.

## Run
```
python smart_campus.py
```
Needs Python 3.8+ only. Uses just the built-in standard library
(sqlite3, tkinter, hashlib, random, datetime). No pip installs.
On some Linux systems install Tkinter first: `sudo apt install python3-tk`

`campus_booking.db` is created in the folder you run the program from and keeps
all data between runs. Delete it to reset.

## Demo accounts
| Role               | Username  | Password    |
|--------------------|-----------|-------------|
| Lecturer           | lecturer1 | lecturer123 |
| Campus Admin (JHB) | admin_jhb | admin123    |
| Campus Admin (DBN) | admin_dbn | admin123    |
| Campus Admin (CPT) | admin_cpt | admin123    |
| Campus Admin (PTA) | admin_pta | admin123    |
| System Operator    | operator  | operator123 |

## Sections inside smart_campus.py
1. Database - SQLite tables and seed data
2. Booking rules - campus policies (add a campus rule set with one new line in POLICIES)
3. Models - User, Lecturer, CampusAdministrator, SystemOperator, Campus, Resource
4. Services - login, resources, bookings, reports
5. GUI - Tkinter screens
6. Main - program start

## Campus policies
| Campus       | Max session | Hours       | Max active | Book ahead | Weekends |
|--------------|-------------|-------------|------------|------------|----------|
| Johannesburg | 120 min     | 08:00-17:00 | 3          | 30 days    | No       |
| Durban       | 180 min     | 07:00-19:00 | 5          | 14 days    | Yes      |
| Cape Town    | 240 min     | 08:00-21:00 | 2          | 60 days    | Yes      |
| Pretoria     | 90 min      | 08:00-16:00 | 4          | 7 days     | No       |

# Flotoken  (Version 1)

Takeaway token system for restaurants. Customers order from a QR link or at the counter, pay, get a token, and see
it on the board when ready. Staff get role-based screens, a full payment record, reports and backups.

Version 1 adds customer accounts (sign up and log in with mobile number and password), order history with
one-tap reorder, ratings, a customer list, a business dashboard for the owner, and a pricing page.

It is also an installable phone app (PWA): customers and staff can add it to their home screen, and the
restaurant owner edits the menu (photos, prices, descriptions, sold-out) from a phone.

## Run (Windows)
Double-click `start.bat`, or in Command Prompt inside this folder:

    python -m pip install Flask
    python app.py

Open http://127.0.0.1:5000. The first time, you create the restaurant and the owner login.
Other devices on the same Wi-Fi: open `http://<laptop-ip>:5000` (run `ipconfig`, read IPv4 Address).
Admin > QR codes prints the customer QR and the TV board QR with your address.

## Customers: accounts, the loop, and the data
Customers must sign up (name, mobile number, password, and a tick to agree to how details are used) before they
can place an order from the app. They can still browse the menu first.

The loop: sign up > order > pay > token > kitchen cooks > ready on the board > collected > rate the order >
My orders > **Order again** in one tap > the owner sees it all in the dashboard and customer list.

- **Walk-in customers:** the cashier uses "Find registered customer" at the counter to attach an account to the
  order (by name or mobile), or just types a name and phone, or leaves both empty.
- **Forgot password:** the owner or cashier opens Admin > Customers > the customer > "Forgot password" and reads the
  temporary password to them. It is shown once. (Automatic reset by OTP needs an SMS provider, see Roadmap.)
- **Delete account:** customers can delete their account in Account. Their old bills stay for your accounts but lose
  the name and number.
- **Privacy rule built in:** mobile numbers are not verified yet, so signing up never reveals old orders that only
  share the same number. A customer sees only orders placed while signed in, or that the cashier attached in person.
- **Customer data** (Admin > Customers): search, sort, see a customer's orders, favourites and ratings, download CSV.
  Only the owner can download the CSV. Cashiers can search and look up.

## Business dashboard (Admin > Dashboard)
Customers, new this week, logged in the last 7 days, repeat customers, orders from app vs counter, share of orders
with an account, average rating and its spread, new customers and orders per day, best customers, staff logins.
This is the view for **one restaurant**. A dashboard across many restaurants needs a multi-restaurant version (Roadmap).

## Pricing (page: /pricing, and Admin > Plan)
- Yearly Rs 7,000. Monthly Rs 649 (7,000 / 12 = 583.33, plus about 11%). Paying yearly saves Rs 788.
- One GST formula, nothing else about GST: GST = price x 18 / 100, total = price + GST. If a price already includes GST,
  price without GST = price / 1.18. Rs 649 + 18% = Rs 765.82; Rs 7,000 + 18% = Rs 8,260. The page has a small
  calculator. Whether GST applies to your bills depends on registration: ask an accountant.
- The numbers live in one place: `PLAN` in `customers.py`.

## Roadmap (not in Version 1)
- Razorpay online payments (the code has a marked place for it in `orders.py`). Until then: simulated "demo" mode, or
  UPI to the restaurant's own ID confirmed by the cashier.
- OTP at sign-up and password reset (needs an SMS provider and DLT registration, about Rs 0.15-0.25 per SMS).
- Automatic WhatsApp (needs the WhatsApp Business API). Today it is a tap-to-send link.
- Many restaurants in one system with your own platform dashboard, and a hosted database so data survives restarts.

## Menu: the owner edits it, no coding
Admin > Menu (works on a phone):
- Add a category, then add items. Each item has a photo, name, price, veg/non-veg, category and short description.
- Tap an item to edit it, move it up/down, or delete it. The switch marks it sold out; customers see it at once.
- Photos are shrunk on the phone to about 150 KB before upload, so a 4 MB camera photo is fine.
- Changing a price never changes old bills. Staff other than the owner cannot edit the menu (cashier and
  kitchen can only use the sold-out switch).

## Phone app (install)
- Android Chrome: open the site, tap "Install app" (or menu > Install app).
- iPhone Safari: Share > Add to Home Screen. The app shows these steps itself.
- Installing needs HTTPS (or localhost). On your laptop over Wi-Fi (`http://192.168...`) the site works in
  the browser, but the phone will not offer install. Put it online (below) to install on phones.
- Offline, the app shows a friendly "You are offline" page and reconnects by itself. Ordering and tracking
  need internet.

## Screens
| Address        | Who            | Purpose |
|----------------|----------------|---------|
| /order         | Customer       | Menu, order, pay, live token tracking (no login) |
| /t/<code>      | Customer       | Private tracking link for one order |
| /board         | Wall TV        | Ready and preparing tokens, chime and voice (no login) |
| /counter       | Cashier        | Take walk-in orders, cash/UPI, UPI QR, sold-out mode |
| /parcel        | Kitchen/Cashier| Cook, mark ready, WhatsApp customer, edit, cancel, hand over |
| /history       | Cashier        | Search any past order; full payment and change record |
| /admin         | Owner          | Reports, menu, staff, settings, QR codes, backup |
| /receipt/<id>  | Cashier        | Printable receipt |

## Roles
- owner: everything
- cashier: counter, payments, refunds, edits, cancel, hand over
- kitchen: start cooking, mark ready, mark items sold out (no money screens)

## Payments: what is real and what is not
- Demo mode (default): phone orders are marked paid instantly. For showing the app only. No money moves.
- UPI mode (Admin > Settings): customer pays your own UPI ID from their UPI app; the cashier checks the money
  arrived and taps "UPI received"; only then can cooking start. This is safe but manual.
- Fully automatic payment confirmation needs a payment gateway (Razorpay, Cashfree, PhonePe PG). It needs a
  business account and a webhook, so it cannot be done offline. The place to add it is marked `TODO(real UPI)`
  in orders.py.

## WhatsApp
When an order is ready, staff tap "WhatsApp customer" and WhatsApp opens with your message ready to send.
Automatic sending needs the WhatsApp Business API. Not included.

## Rules enforced by the server
- Unpaid orders cannot be cooked or handed over. Items lock once an order is ready.
- Removing an item after cooking starts needs staff approval. An order always keeps one item (cancel instead).
- Item names and prices are copied into each order, so menu changes never alter old bills.
- Sold-out items cannot be ordered anywhere. Every change is logged with the staff name.
- Tokens restart each day. Login attempts and phone orders are rate limited.

## Files
    app.py        app setup, security headers, error handling
    db.py         tables and settings
    auth.py       login, roles, first-run setup
    orders.py     orders, payments, status rules, customer API
    admin.py      menu, staff, settings, reports, CSV, backup
    pages.py      HTML routes
    templates/    screens        static/  css, js, icons, service worker (sw.js)
    tests/        automated tests
    render.yaml   one-click Render setup       requirements.txt  Flask, gunicorn

## Tests
    python -m unittest discover -s tests -v

## Put it on GitHub (Windows Command Prompt, inside this folder)
Create an empty repository on github.com first (no README), then:

    git init
    git add .
    git commit -m "Flotoken first version"
    git branch -M main
    git remote add origin https://github.com/<your-username>/flotoken.git
    git push -u origin main

`.gitignore` keeps your database (`instance/`, `*.db`), secret key and `.env` out of GitHub. Never upload them:
the database holds customer phone numbers and the owner's password hash.

## Put it on Render
1. Push to GitHub (above). On render.com choose New > Blueprint and pick the repository. It reads `render.yaml`.
2. Render asks for OWNER_USERNAME and OWNER_PASSWORD. Use a strong password. These create the first owner login.
3. Open the address Render gives you (https). Sign in at /login, then use Admin > QR codes.

Free plan, be clear about this: the service sleeps after 15 minutes without visitors (about a minute to wake
up) and **all data is erased on every restart or deploy**. Menu edits, orders, staff accounts **and customer accounts** are lost; the
owner and sample menu are recreated from the environment variables. Use free only to demo.
For a real restaurant, switch to a paid plan and enable the persistent disk in `render.yaml` (remove the `#`
lines for `disk` and `DB_FILE`). Check the current price on render.com/pricing. With a disk, keep one instance.
Still download a backup weekly (Admin > Settings).

## Before real use
1. Set a strong owner password. Create one login per staff member.
2. Keep the laptop plugged in and set it not to sleep (if running locally). Download a backup weekly.
3. Local Wi-Fi only: if the router restarts, screens reconnect by themselves within seconds.
4. Online: HTTPS, a SECRET_KEY (Render generates one), gunicorn, and a persistent disk (see above).
5. Data in instance/parcel.db (or the disk) is the whole business record. Do not delete it.

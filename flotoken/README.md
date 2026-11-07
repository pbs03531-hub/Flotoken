# Flotoken  (Version 1, many restaurants)

Takeaway tokens for restaurants. One server holds **many restaurants**. Each restaurant has its own staff, menu, orders and database file. Customers have **one account that works at every restaurant**.

## How people enter (the start screen, `/`)

| Who | Taps | Goes to |
|---|---|---|
| Restaurant owner or staff | **Restaurant login** | `/staff`: choose the restaurant, enter username and password, then land on Admin, Counter or Parcel screen by role |
| Customer | **I am a customer** | `/customer`: sign up or log in, pick any restaurant, order, track the token, see past orders from every restaurant |
| You (Flotoken owner) | small link **Flotoken team** | `/platform`: your private dashboard |

## Your owner dashboard (`/platform`)
First visit on a new server asks you to create your owner username and password (or set `PLATFORM_USERNAME` and `PLATFORM_PASSWORD`).
* **Overview**: restaurants, paying vs trial, monthly income, expired plans, customers, orders today and in 30 days, daily charts, every restaurant with its usage.
* **Restaurants**: add a restaurant (name, web address, owner login, plan, sample menu), edit plan and "paid until", suspend, and **Reset owner login** when an owner forgets the username or password. You get a "share these details" box with the login page, username and password to send on WhatsApp.
* **Customers**: search by name or phone, see how many restaurants each uses, give a temporary password to someone who forgot theirs.

## Forgot a password?
* Restaurant owner or staff owner: you open **Restaurants > Reset owner login** in `/platform`.
* Restaurant staff (cashier, kitchen): their owner resets them in Admin > Staff.
* Customer: you reset it in `/platform` > Customers.
* You: change `PLATFORM_PASSWORD` in Render > Environment and redeploy. It is re-applied at start-up.

## Where things live
Every restaurant is at `/r/<web-address>/` (for example `/r/betty/order`, `/r/betty/counter`). Data: `platform.db` (restaurants, customers, your login) and `restaurants/<address>.db` (one file per restaurant), all inside `DATA_DIR` (default folder `instance/`).

## Run (Windows)
Double-click `start.bat`, or in Command Prompt inside this folder:

    python -m pip install Flask
    python app.py

Open http://127.0.0.1:5000. The first time, you create the restaurant and the owner login.
Other devices on the same Wi-Fi: open `http://<laptop-ip>:5000` (run `ipconfig`, read IPv4 Address).
Admin > QR codes prints the customer QR and the TV board QR with your address.

## Customers: accounts, the loop, and the data
Customers sign up once on Flotoken (the account works at every restaurant). They must sign up (name, mobile number, password, and a tick to agree to how details are used) before they
can place an order from the app. They can still browse the menu first.

The loop: sign up > order > pay > token > kitchen cooks > ready on the board > collected > rate the order >
My orders > **Order again** in one tap > the owner sees it all in the dashboard and customer list.

- **Walk-in customers:** the cashier uses "Find registered customer" at the counter to attach an account to the
  order (by name or mobile), or just types a name and phone, or leaves both empty.
- **Forgot password:** the Flotoken owner resets it in `/platform` > Customers and tells the customer a temporary password. (Automatic reset by OTP needs an SMS provider, see Roadmap.)
- **Delete account:** customers can delete their account in Account. Their old bills stay in each restaurant's books but lose
  the name and number, at every restaurant they used.
- **Privacy rule built in:** mobile numbers are not verified yet, so signing up never reveals old orders that only
  share the same number. A customer sees only orders placed while signed in, or that the cashier attached in person.
- **Customer data** (Admin > Customers): each restaurant sees only customers who ordered from it: search, sort, orders, favourites,
  ratings, CSV (owner only). A cashier can find a registered customer by exact 10-digit mobile number to attach an order.

## Business dashboard (Admin > Dashboard)
Customers, new this week, logged in the last 7 days, repeat customers, orders from app vs counter, share of orders
with an account, average rating and its spread, new customers and orders per day, best customers, staff logins.
This is the view for **one restaurant**. Your view across all restaurants is `/platform`.

## Pricing (page: /pricing, and Admin > Plan)
- Yearly Rs 7,000. Monthly Rs 649 (7,000 / 12 = 583.33, plus about 11%). Paying yearly saves Rs 788.
- One GST formula, nothing else about GST: GST = price x 18 / 100, total = price + GST. If a price already includes GST,
  price without GST = price / 1.18. Rs 649 + 18% = Rs 765.82; Rs 7,000 + 18% = Rs 8,260. The page has a small
  calculator. Whether GST applies to your bills depends on registration: ask an accountant.
- The numbers live in one place: `PLAN` in `pricing.py`.

## Roadmap (not in Version 1)
- Razorpay online payments (the code has a marked place for it in `orders.py`). Until then: simulated "demo" mode, or
  UPI to the restaurant's own ID confirmed by the cashier.
- OTP at sign-up and password reset (needs an SMS provider and DLT registration, about Rs 0.15-0.25 per SMS).
- Automatic WhatsApp (needs the WhatsApp Business API). Today it is a tap-to-send link.
- Enforcing plans (today "paid until" and plan are recorded and shown, not blocked), and a hosted database so data survives restarts without a disk.

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

## Screens (restaurant screens live under `/r/<address>`)
| Address        | Who            | Purpose |
|----------------|----------------|---------|
| /              | Everyone       | Start screen: Restaurant login or Customer |
| /staff         | Staff          | Choose restaurant, then sign in |
| /customer      | Customer       | Sign up / log in, pick a restaurant, all my orders |
| /platform      | You            | Flotoken owner dashboard |
| /r/&lt;address&gt;/order | Customer | Menu, order (login needed), pay, live token tracking |
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
Owner picks in Admin > Settings > Payments what customers see at checkout:
- **Pay at the counter** (default for new restaurants, nothing to set up): the customer orders on the phone, gets a token, and pays cash or scans the shop's UPI QR at the counter. The cashier taps Cash or UPI received, then the kitchen can cook.
- **Pay by UPI**: customer pays your UPI ID from their UPI app (needs your UPI ID in Settings); the cashier confirms the money arrived.
- **Customer chooses**: both options are shown at checkout.
- **Demo mode**: simulated payment, for showing the app only.
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
    portal.py     start screen, your owner dashboard, restaurants, platform API
    customers.py  customer accounts (global), restaurant-side customer data
    pricing.py    plan prices and the GST formula
    auth.py       staff login and roles (per restaurant)
    orders.py     orders, payments, status rules
    admin.py      menu, staff, settings, reports, CSV, backup
    pages.py      HTML routes
    templates/    screens        static/  css, js, icons, service worker (sw.js)
    tests/        automated tests
    render.yaml   one-click Render setup       requirements.txt  Flask, gunicorn

## Tests
    python -m unittest discover -s tests -v

## Put it on GitHub
Upload the **contents** of this folder (app.py, requirements.txt, render.yaml, templates, static ...) to the **top level** of the repository.
If you drag in the folder itself, Render cannot find `requirements.txt` (error "Could not open requirements file"). In that case, either
re-upload the contents, or in Render > Settings set **Root Directory** to the folder name.

With git (Windows Command Prompt, inside this folder), after creating an empty repository on github.com:

    git init
    git add .
    git commit -m "Flotoken V1"
    git branch -M main
    git remote add origin https://github.com/<your-username>/Flotoken.git
    git push -u origin main

`.gitignore` keeps databases (`instance/`, `*.db`), the secret key and `.env` out of GitHub. Never upload them: they hold customers'
phone numbers and password hashes.

## Put it on Render
1. Push to GitHub. On render.com choose New > Blueprint and pick the repository. It reads `render.yaml`.
2. Render asks for **PLATFORM_USERNAME** and **PLATFORM_PASSWORD**: this is YOUR login for `/platform`. Use a strong password and write it down.
3. Open the address Render gives you. The start screen appears with the two options. Tap **Flotoken team** > log in > **Restaurants > Add restaurant**.
4. Give the owner the details from the "share these details" box.

The blueprint also creates a demo restaurant (login `demo` / `demo1234`) so you can try it at once. Delete those three variables
(`RESTAURANT_NAME`, `OWNER_USERNAME`, `OWNER_PASSWORD`) before real use, then add real restaurants from `/platform`.

If the build says the Python version is a problem, add an environment variable `PYTHON_VERSION` = `3.13.5` (the app is tested on 3.13).

Free plan, be clear about this: the service sleeps after 15 minutes without visitors (about a minute to wake up) and **all data is
erased on every restart or deploy**: restaurants you added, menus, orders, staff and customer accounts. Only your owner login and the
demo restaurant come back (from the environment variables). Use free only to demo. For real restaurants, switch to a paid plan and enable the
persistent disk in `render.yaml` (remove the `#` on the `disk` and `DATA_DIR` lines). Check the price on render.com/pricing.
With a disk, keep one instance. Each restaurant can download its own backup (Admin > Settings); `/var/data` holds all of them.

## Before real use
1. Set a strong owner password. Create one login per staff member.
2. Keep the laptop plugged in and set it not to sleep (if running locally). Download a backup weekly.
3. Local Wi-Fi only: if the router restarts, screens reconnect by themselves within seconds.
4. Online: HTTPS, a SECRET_KEY (Render generates one), gunicorn, and a persistent disk (see above).
5. `DATA_DIR` (folder `instance/` locally, the disk on Render) is the whole record of every restaurant. Do not delete it.

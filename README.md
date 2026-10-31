# Brightloop – Subscription Management System

A web-based Subscription Management System developed to simplify subscription operations, automate billing workflows, manage customer payments, and monitor business revenue.

## 🚀 How to Run the Project

Follow these steps to run Brightloop on your local machine.

**Prerequisites:** Python 3.10 or later and Git.

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

### 2. Open the project folder

```bash
cd brightloop_subscription_system
```

### 3. Create a virtual environment

```bash
python -m venv .venv
```

### 4. Activate the virtual environment

For Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 5. Install the required packages

```bash
python -m pip install -r requirements.txt
```

### 6. Run the application

```bash
python app.py
```

### 7. Open in your browser

Visit:

```text
http://127.0.0.1:5000
```

**Demo Admin Login**

- Email: `admin@brightloop.demo`
- Password: `Brightloop@123`

---

## 1. Project Overview

Brightloop is designed to manage the complete subscription lifecycle in one centralized platform.

It helps businesses manage customers, products, subscription plans, quotations, recurring invoices, discounts, payments, and revenue reports.

The system reduces manual work and makes subscription management easier and more organized.

## 2. Key Features

### Dashboard
- View total customers.
- Monitor active subscriptions.
- Track revenue received.
- View outstanding balances.
- Monitor overdue invoices.
- View recent billing activity.

### Customer Management
- Add and manage customer records.
- Maintain customer information.
- Provide customers with access to their own subscription and invoice details.

### Product Management
- Create and manage products.
- Define product types.
- Set sales prices and cost prices.
- Add product variants and additional charges.
- Maintain product notes.

### Subscription Plan Management
- Create subscription plans.
- Set subscription prices.
- Select billing frequencies: daily, weekly, monthly, and yearly.
- Configure minimum quantities.

### Quotation Management
- Create quotations for customers.
- Manage quotation details.
- Convert quotations into subscriptions.

### Subscription Management
- Create customer subscriptions.
- Select subscription plans.
- Set start and expiry dates.
- Apply discounts.
- Manage subscription status.
- Pause, resume, and close subscriptions.

### Invoice Management
- Generate invoices from subscriptions.
- Calculate applicable taxes.
- Track invoice amounts and payment status.
- Prevent duplicate invoice generation for the same billing period.
- View invoice details.

### Discount Management
- Create discounts.
- Configure fixed or percentage-based discounts.
- Manage discount availability and usage conditions.

### Payment Management
- Record customer payments.
- Select payment methods.
- Maintain payment history.
- Track paid and outstanding amounts.

### Reports and Revenue Monitoring
- Monitor business revenue.
- Review financial information.
- Track subscription and invoice activity.

### User and Access Management
- Admin access for managing the workspace.
- Staff account management.
- Customer access to their own account information.

## 3. Technology Stack

| Component | Technology |
|---|---|
| Backend | Python |
| Web Framework | Flask |
| Frontend | HTML, CSS, Jinja2 |
| Database | SQLite |
| Scheduling | APScheduler |
| PDF Generation | ReportLab |
| Spreadsheet Support | OpenPyXL |
| Payment Integration Library | Stripe |

## 4. Project Structure

```text
brightloop_subscription_system/
│
├── app.py
├── requirements.txt
├── README.md
├── templates/
│   ├── base.html
│   ├── login.html
│   └── page.html
│
├── static/
│   └── style.css
│
└── instance/
    └── Database files (if generated)
```

*The exact database and supporting file names may vary depending on the application version.*

## 5. Testing

The application can be tested using the following workflow:

1. Create a customer.
2. Add a product and subscription plan.
3. Create an active subscription.
4. Generate an invoice.
5. Record a full or partial payment.
6. Verify the invoice status.
7. Check the dashboard for updated financial information.

## 6. Important Notes

This project is an educational demonstration build.

Some features may require additional configuration or development before production use.

- Real payment gateway transactions require proper Stripe configuration.
- Email notifications require an email service configuration.
- Scheduled billing requires the scheduler to be configured and running.
- Authentication and password management should be reviewed before public deployment.
- Tax rules and financial calculations should be configured according to actual business requirements.
- Production deployment requires secure environment variables, database backups, and additional security testing.

## 7. Future Enhancements

- Automated recurring billing.
- Email and renewal notifications.
- Advanced financial analytics.
- Secure online payment processing.
- Customer self-service portal improvements.
- Advanced role-based permissions.
- Improved subscription renewal management.
- Exportable financial reports.

## 8. Project Objective

The main objective of Brightloop is to provide a centralized and user-friendly platform that simplifies subscription management, reduces repetitive administrative work, improves billing accuracy, and provides better visibility into business revenue.

---

**Project Name:** Brightloop
**Category:** Web Application / Business Management System
**Status:** Educational Demo Build
import os

app_name = "snrg_supplychain"
app_title = "SNRG Supply Chain"
app_publisher = "SNRG Electricals"
app_description = "Supply Chain, Freight & Carton Management for SNRG Electricals"
app_email = "admin@snrgelectricals.com"
app_license = "mit"

# Fixtures — data that ships with the app and is imported on bench migrate
fixtures = [
    {"dt": "Freight Zone"}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/snrg_supplychain/css/snrg_supplychain.css"
# app_include_js = "/assets/snrg_supplychain/js/snrg_supplychain.js"

# include js, css files in header of web template
# web_include_css = "/assets/snrg_supplychain/css/snrg_supplychain.css"
# web_include_js = "/assets/snrg_supplychain/js/snrg_supplychain.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "snrg_supplychain/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
page_js = {"packed_carton_touch": "public/js/packed_carton_touch.js"}

# include js in doctype views
doctype_js = {
    "Item": "public/js/item_custom.js",
    "Sales Order": "public/js/sales_order_custom.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "snrg_supplychain.utils.jinja_methods",
# 	"filters": "snrg_supplychain.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "snrg_supplychain.install.before_install"
# after_install = "snrg_supplychain.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "snrg_supplychain.uninstall.before_uninstall"
# after_uninstall = "snrg_supplychain.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "snrg_supplychain.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"snrg_supplychain.tasks.all"
# 	],
# 	"daily": [
# 		"snrg_supplychain.tasks.daily"
# 	],
# 	"hourly": [
# 		"snrg_supplychain.tasks.hourly"
# 	],
# 	"weekly": [
# 		"snrg_supplychain.tasks.weekly"
# 	],
# 	"monthly": [
# 		"snrg_supplychain.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "snrg_supplychain.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "snrg_supplychain.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "snrg_supplychain.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["snrg_supplychain.utils.before_request"]
# after_request = ["snrg_supplychain.utils.after_request"]

# Job Events
# ----------
# before_job = ["snrg_supplychain.utils.before_job"]
# after_job = ["snrg_supplychain.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"snrg_supplychain.auth.validate"
# ]

# your_custom_app/overrides/user.py

from frappe.core.doctype.user.user import User, _update_password

class CustomUser(User):
	def set_new_password(self, new_password=None):
		"""Set New Password for user"""
		if new_password and not self.flags.in_insert:
			_update_password(user=self.name, pwd=new_password, logout_all_sessions=self.logout_all_sessions)
			
import mysql.connector
def get_db():
	return mysql.connector.connect(
		host='localhost',
		user='root',
		password='georgeorwell#1984',
		database='tara_system'
	)

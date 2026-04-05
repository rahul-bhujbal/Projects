import json

class Database:
    def add_data(self,name,email,password):
        with open('demodb.json','r') as rf:
            database = json.load(rf)

        if email in database:
            return 0
        else:
            database[email] = [name,password]
            with open('demodb..json','w') as wf:
                json.dump(database,wf)
            return 1
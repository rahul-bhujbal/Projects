from tkinter import *
from demomydb import Database
from tkinter import messagebox

class NLPApp:
    def __init__(self):
        self.mydbo = Database()
        # load login gui
        self.root = Tk()
        self.root.title('NLPApp')
        self.root.geometry('600x650')
        self.root.configure(bg='#bb95c7')
        self.login_gui()
        self.root.mainloop()

    def login_gui(self):
        self.clear()
        heading = Label(self.root, text='NLPApp', bg='#bb95c7', fg='white')
        heading.pack(pady=(30, 30))
        heading.configure(font=('verdana', 24, 'bold'))

        label1 = Label(self.root, text='Enter Email')
        label1.pack(pady=(10, 10))
        self.email_input = Entry(self.root, width=30)
        self.email_input.pack(pady=(5, 10))

        label2 = Label(self.root, text='Enter Password')
        label2.pack(pady=(10, 10))
        self.password_input = Entry(self.root, width=30, show='.')
        self.password_input.pack(pady=(5, 10))

        login_button = Button(self.root, text='Login', width=10)
        login_button.pack(pady=(10, 10))

        label3 = Label(self.root, text='Not a member?')
        label3.pack(pady=(10, 10))

        redairect_button = Button(self.root, text='Register Now',command=self.register_gui)
        redairect_button.pack(pady=(10, 10))

    def register_gui(self):
        self.clear()

        heading = Label(self.root, text='NLPApp', bg='#bb95c7', fg='white')
        heading.pack(pady=(30, 30))
        heading.configure(font=('verdana', 24, 'bold'))

        label0 = Label(self.root, text='Enter Name')
        label0.pack(pady=(10, 10))
        self.name_input = Entry(self.root, width=30)
        self.name_input.pack(pady=(5, 10))

        label1 = Label(self.root, text='Enter Email')
        label1.pack(pady=(10, 10))
        self.email_input = Entry(self.root, width=30)
        self.email_input.pack(pady=(5, 10))

        label2 = Label(self.root, text='Enter Password')
        label2.pack(pady=(10, 10))
        self.password_input = Entry(self.root, width=30, show='.')
        self.password_input.pack(pady=(5, 10))

        register_button = Button(self.root, text='Register', width=10,command=self.perform_register)
        register_button.pack(pady=(10, 10))

        label3 = Label(self.root, text='Alreday  a member?')
        label3.pack(pady=(10, 10))

        redairect_button = Button(self.root, text='Login Now',command=self.login_gui)
        redairect_button.pack(pady=(10, 10))

    def clear(self):
        # clear the existing gui
        for i in self.root.pack_slaves():
            print(i)
            i.destroy()

    def perform_register(self):
        # fetch data from gui
        name = self.name_input.get()
        email = self.email_input.get()
        password = self.password_input.get()
        # print(name,email,password)
        response = self.mydbo.add_data(name, email, password)

        if response:
            print('Registration sucessful')
            messagebox.showinfo('Sucess', 'Registration Sucessfully! You can login now')
        else:
            print('email exist')
            messagebox.showerror('Error', 'Email already exists')


obj = NLPApp()
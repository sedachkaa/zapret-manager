import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("Zapret Manager — test")
app.geometry("800x500")

label = ctk.CTkLabel(app, text="Окружение работает ✅", font=("Arial", 20))
label.pack(pady=40)

app.mainloop()
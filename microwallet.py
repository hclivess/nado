import json
import random
import threading
import time

import customtkinter
import requests

from block_ops import fee_over_blocks
from config import get_timestamp_seconds, get_port
from keys import load_keys
from logs import get_logger
from peers import load_ips
from transaction_ops import create_transaction, to_readable_amount, to_raw_amount


def address_copy():
    app.clipboard_clear()
    app.clipboard_append(address)


def insert_clipboard(where):
    where.delete(0, customtkinter.END)
    where.insert(customtkinter.INSERT, app.clipboard_get())


class Wallet:
    def __init__(self):
        self.target = random.choice(load_ips())
        self.port = get_port()
        self.connected = True
        self.refresh_counter = 10

    def reconnect(self):
        self.target = random.choice(load_ips())
        self.port = get_port()
        try:
            url = f"http://{self.target}:{self.port}/status"
            requests.get(url, timeout=3)
            self.connected = True
            connection_label.set_text("Reconnected")
        except Exception as e:
            print(f"Failed to reconnect: {e}")

    def get_balance(self):
        try:
            url = f"http://{self.target}:{self.port}/get_account?address={address}"
            balance_raw = requests.get(url, timeout=3)
            balance = to_readable_amount(json.loads(balance_raw.text)["account_balance"])
            balance_var.set(balance)
            connection_label.set_text(f"Connected to {self.target}")

            self.refresh_counter -= 1
            if self.refresh_counter < 1:
                status_label.set_text("")

        except Exception as e:
            print(f"Could not connect to get balance: {e}")
            connection_label.set_text("Disconnected")
            self.connected = False

    def send_transaction(self):
        transaction = create_transaction(sender=address,
                                         recipient=recipient.get(),
                                         amount=to_raw_amount(int(amount.get())),
                                         data={"data": data.get(), "command": command.get()},
                                         fee=int(fee.get()),
                                         public_key=public_key,
                                         private_key=private_key,
                                         timestamp=get_timestamp_seconds())

        print(transaction)
        try:
            url = f"http://{self.target}:{self.port}/submit_transaction?data={json.dumps(transaction)}"
            result = json.loads(requests.get(url, timeout=3).text)
            status_label.set_text(f"{result['message']}")
            self.refresh_counter = 10

        except Exception as e:
            print(f"Could not connect to submit transaction: {e}")
            connection_label.set_text("Disconnected")
            self.connected = False


def exit_app():
    refresh.quit = True
    app.quit()


class RefreshClient(threading.Thread):
    def __init__(self, wallet):
        threading.Thread.__init__(self)
        self.quit = False
        self.wallet = wallet

    def run(self):
        while not self.quit:
            wallet.get_balance()

            if not wallet.connected:
                wallet.reconnect()
            time.sleep(1)


if __name__ == "__main__":
    logger = get_logger(file="wallet.log")

    key_dict = load_keys()
    address = key_dict["address"]
    private_key = key_dict["private_key"]
    public_key = key_dict["public_key"]

    customtkinter.set_appearance_mode("dark")
    customtkinter.set_default_color_theme("green")

    app = customtkinter.CTk()
    app.geometry("600x350")
    app.title("NADO MicroWallet")
    app.resizable(0, 0)

    status_label = customtkinter.CTkLabel(master=app, text="", anchor="w")
    status_label.grid(row=7, column=1, columnspan=10, padx=2, pady=2, sticky="w")
    connection_label = customtkinter.CTkLabel(master=app, text="", anchor="w")
    connection_label.grid(row=8, column=1, columnspan=10, padx=2, pady=2, sticky="w")

    sender_button = customtkinter.CTkButton(master=app, text="Sender:", command=lambda: address_copy(), width=50)
    sender_button.grid(row=0, column=0, padx=2, pady=2, sticky="e")

    address_label = customtkinter.CTkLabel(master=app, text=address)
    address_label.grid(row=0, column=1, sticky="w")

    balance_var = customtkinter.StringVar()

    balance_label = customtkinter.CTkLabel(master=app, text="Balance:", anchor="e")
    balance_label.grid(row=1, column=0)
    balance = customtkinter.CTkLabel(master=app, textvariable=balance_var)
    balance.grid(row=1, column=1, sticky="w")

    recipient_button = customtkinter.CTkButton(master=app, text="Recipient:",
                                               command=lambda: insert_clipboard(recipient), width=50)
    recipient_button.grid(row=2, column=0, padx=2, pady=2, sticky="e")

    recipient = customtkinter.CTkEntry(master=app, width=300)
    recipient.grid(row=2, column=1, padx=2, pady=2, sticky="w")

    init_amount = customtkinter.StringVar()
    init_amount.set("0")
    amount_label = customtkinter.CTkLabel(master=app, text="Amount:", anchor="e")
    amount_label.grid(row=3, column=0, padx=2, pady=2)
    amount = customtkinter.CTkEntry(master=app, textvariable=init_amount)
    amount.grid(row=3, column=1, padx=2, pady=2, sticky="w")

    init_fee = customtkinter.StringVar()
    init_fee.set(fee_over_blocks(logger=logger))
    fee_label = customtkinter.CTkLabel(master=app, text="Fee:", anchor="e")
    fee_label.grid(row=4, column=0, padx=2, pady=2)
    fee = customtkinter.CTkEntry(master=app, textvariable=init_fee)
    fee.grid(row=4, column=1, padx=2, pady=2, sticky="w")

    command_label = customtkinter.CTkLabel(master=app, text="Command:", anchor="e")
    command_label.grid(row=5, column=0, padx=2, pady=2)
    command = customtkinter.CTkEntry(master=app)
    command.grid(row=5, column=1, padx=2, pady=2, sticky="w")

    data_label = customtkinter.CTkLabel(master=app, text="Data:", anchor="e")
    data_label.grid(row=6, column=0, padx=2, pady=2)
    data = customtkinter.CTkEntry(master=app, width=300)
    data.grid(row=6, column=1, padx=2, pady=2, sticky="w")

    send_button = customtkinter.CTkButton(master=app, text="Send", command=lambda: wallet.send_transaction())
    send_button.grid(row=9, column=1, padx=2, pady=2, sticky="w")

    quit_button = customtkinter.CTkButton(master=app, text="Quit", command=lambda: exit_app())
    quit_button.grid(row=10, column=1, padx=2, pady=2, sticky="w")

    wallet = Wallet()
    refresh = RefreshClient(wallet=wallet)
    refresh.start()
    app.mainloop()

import email
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
import select
import smtplib
import socket
import sys
import re
import pathlib
import glosocket
import gloutils
import os.path


class Server:
    """Serveur mail @glo2000.ca."""

    def __init__(self) -> None:
        """
        Initializes the server by setting up the `_server_socket` and putting it in listening mode.

        Initializes the following attributes:
        - `_client_socs`: a list of client sockets.
        - `_logged_users`: a dictionary associating each client socket with a username.

        Ensures that the server data folders exist.
        """
        # Ensure the server data directories exist
        if not os.path.exists(gloutils.SERVER_DATA_DIR):
            os.mkdir(gloutils.SERVER_DATA_DIR)
        if not os.path.exists(gloutils.SERVER_LOST_DIR):
            os.mkdir(gloutils.SERVER_LOST_DIR)

        # Initialize attributes
        self._client_socs = []
        self._logged_users = {}

        try:
            # Create and configure the server socket
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("127.0.0.1", gloutils.APP_PORT))
            self._server_socket.listen()
        except glosocket.GLOSocketError:
            print("Error initializing the server socket. Check if the port is available.")

    def cleanup(self) -> None:
        """
        Closes all residual connections.

        Iterates through all client sockets in `_client_socs` and closes each socket.
        Finally, closes the server socket.
        """
        # Close all client sockets
        for client_soc in self._client_socs:
            client_soc.close()

        # Close the server socket
        self._server_socket.close()

    def _accept_client(self) -> None:
        """
        Accepts a new client.

        Accepts a new client connection using the server socket.
        The new client socket is added to the list of client sockets (_client_socs).
        """
        client_soc, address = self._server_socket.accept()
        self._client_socs.append(client_soc)

    def _remove_client(self, client_soc: socket.socket) -> None:
        """
        Removes the client from data structures and closes its connection.

        Iterates through the logged users to find and remove the client socket.
        Removes the client socket from the list of client sockets (_client_socs).
        Closes the client socket.
        """
        # Find and remove the client from logged users
        for nom, s in self._logged_users.items():
            if client_soc == s:
                self._logged_users.pop(nom)

        # Remove the client socket from the list of client sockets
        self._client_socs.remove(client_soc)

        # Close the client socket
        client_soc.close()

    def _logout(self, client_soc: socket.socket) -> None:
        """
        Disconnects a user.

        Finds the username associated with the given client socket and removes
        the user from the logged users dictionary.

        Parameters:
        - client_soc (socket.socket): The client socket to disconnect.
        """
        nom = None

        # Iterate through logged users to find the username associated with the client socket
        for key, value in self._logged_users.items():
            if value == client_soc:
                nom = key

        # Remove the user from the logged users dictionary
        if nom is not None:
            del self._logged_users[nom]

    def _create_account(self, client_soc: socket.socket,
                        payload: gloutils.AuthPayload
                        ) -> gloutils.GloMessage:
        """
        Creates an account based on the payload data.

        If the credentials are valid, creates the user's folder,
        associates the socket with the new user, and returns success.
        Otherwise, returns an error message.

        Parameters:
        - client_soc (socket.socket): The client socket associated with the user.
        - payload (gloutils.AuthPayload): Authentication payload containing username and password.

        Returns:
        - gloutils.GloMessage: Success message or error message.
        """

        username = payload["username"]
        password = payload["password"]
        user_valid = False
        password_valid = False

        # Check if the username is already taken
        for user_index in self._logged_users:
            if username.lower() == self._logged_users[user_index].lower():
                return gloutils.GloMessage(header=gloutils.Headers.ERROR)

        # Check if the username contains at least one letter
        if re.search(r"[a-zA-Z]", username):
            user_valid = True

        # Check if the password length is greater than 9
        if len(password) > 9:
            password_valid = True

        # If credentials are not valid, send an error message
        if not (password_valid and user_valid):
            return glosocket.send_msg(client_soc, json.dumps(gloutils.GloMessage(header=gloutils.Headers.ERROR)))

        # Add the user to the logged users dictionary
        self._logged_users[username] = client_soc

        # Hash the password using SHA-3 224
        hashed_password = hashlib.sha3_224(password.encode('utf-8')).hexdigest()

        # Create the user's folder and store the hashed password
        path = os.path.join(gloutils.SERVER_DATA_DIR, username)
        if not os.path.exists(path):
            os.mkdir(path)
            with open(os.path.join(path, gloutils.PASSWORD_FILENAME), "a") as f:
                f.write(hashed_password)

        return glosocket.send_msg(client_soc, json.dumps(gloutils.GloMessage(header=gloutils.Headers.OK)))

    def _login(self, client_soc: socket.socket, payload: gloutils.AuthPayload
               ) -> gloutils.GloMessage:
        """
        Verifies that the provided data corresponds to an existing account.

        If the credentials are valid, associates the socket with the user and
        returns success. Otherwise, returns an error message.

        Parameters:
        - client_soc (socket.socket): The client socket associated with the user.
        - payload (gloutils.AuthPayload): Authentication payload containing username and password.

        Returns:
        - gloutils.GloMessage: Success message or error message.
        """

        username = payload["username"]
        password = payload["password"]

        # Check if the username exists in the logged users dictionary
        if username in self._logged_users:
            # Retrieve the associated socket
            existing_socket = self._logged_users[username]

            # Check if the provided socket matches the one associated with the username
            if existing_socket == client_soc:
                return glosocket.send_msg(client_soc, json.dumps(gloutils.GloMessage(header=gloutils.Headers.OK)))
            else:
                return glosocket.send_msg(client_soc, json.dumps(gloutils.GloMessage(header=gloutils.Headers.ERROR)))
        else:
            return glosocket.send_msg(client_soc, json.dumps(gloutils.GloMessage(header=gloutils.Headers.ERROR)))

    def _get_email_list(self, client_soc: socket.socket
                        ) -> gloutils.GloMessage:
        """
        Retrieves the list of emails for the user associated with the socket.
        The list elements are constructed using the SUBJECT_DISPLAY template
        and are ordered from most recent to oldest.

        The absence of an email is not an error, but an empty list.

        Parameters:
        - client_soc (socket.socket): The client socket associated with the user.

        Returns:
        - gloutils.GloMessage: A message containing the list of emails.
        """

        nom_client = ""
        liste_mail = []

        for nom, soc in self._logged_users.items():
            if soc == client_soc:
                nom_client = nom

        chemin_general = "{nom_dossier}/{nom_cli}".format(nom_dossier=gloutils.SERVER_DATA_DIR, nom_cli=nom_client)

        # Check if the 'email' directory exists
        if os.path.exists(chemin_general + "/email"):
            liste = os.listdir(chemin_general + "/email")
            for o, courr in enumerate(liste):
                # Check if the file path exists
                if os.path.exists(os.path.join(chemin_general + "/email", courr)):
                    with open(chemin_general + "/email/" + courr, 'r') as f:
                        contenu = json.load(f)
                        info_mail = gloutils.SUBJECT_DISPLAY.format(number=str(o + 1),
                                                                    sender=contenu["sender"],
                                                                    subject=contenu["subject"],
                                                                    date=contenu["date"])
                        liste_mail.append(info_mail)
        else:
            # If 'email' directory does not exist, return an empty list
            glosocket.send_msg(client_soc, json.dumps(liste_mail))
            return gloutils.GloMessage()

        # Send the list of emails to the client
        glosocket.send_msg(client_soc, json.dumps(liste_mail))
        return gloutils.GloMessage()

    def _get_email(self, client_soc: socket.socket,
                   payload: gloutils.EmailChoicePayload
                   ) -> gloutils.GloMessage:
        """
        Retrieves the content of the email in the user's folder associated
        with the socket.

        Parameters:
        - client_soc (socket.socket): The client socket associated with the user.
        - payload (gloutils.EmailChoicePayload): Payload containing the choice of email.

        Returns:
        - gloutils.GloMessage: A message containing the content of the email.
        """

        nom_client = ''
        for nom, soc in self._logged_users.items():
            if soc == client_soc:
                nom_client = nom

        choix = payload['choice'] - 1
        courr = ""

        chemin_general = "{nom_dossier}/{nom_cli}".format(nom_dossier=gloutils.SERVER_DATA_DIR, nom_cli=nom_client)

        liste = os.listdir(chemin_general + "/email")

        for o, cour in enumerate(liste):
            if o == choix:
                courr = cour

        with open(chemin_general + "/email/" + courr, 'r') as f:
            lr_mail = f.read()

        # Send the content of the email to the client
        glosocket.send_msg(client_soc, lr_mail)
        return gloutils.GloMessage()

    def _get_stats(self, client_soc: socket.socket) -> gloutils.GloMessage:
        """
        Retrieves the number of emails and the size of the folder and files
        of the user associated with the socket.

        Parameters:
        - client_soc (socket.socket): The client socket associated with the user.

        Returns:
        - gloutils.GloMessage: A message containing the number of emails and the size.
        """

        print("Afficher les statistiques:")
        nmbr_ml = 0
        chemin_general = "{nom_dossier}/{nom_cli}".format(nom_dossier=gloutils.SERVER_DATA_DIR, nom_cli=client_soc)
        lst = os.listdir(chemin_general + "/email")

        for i in lst:
            nmbr_ml += 1

        # Calculate the total size of the files in the email folder
        tlle = sum(os.path.getsize(os.path.join(chemin_general + "/email", f)) for f in lst)

        # Send the number of emails and the total size to the client
        glosocket.send_msg(client_soc, json.dumps({"number_of_emails": nmbr_ml, "total_size": tlle}))
        return gloutils.GloMessage()

    def _send_email(self, payload: gloutils.EmailContentPayload) -> gloutils.GloMessage:
        """
        Determine if the email is internal or external and:
        - If the email is internal, write the message as-is in the recipient's folder.
        - If the recipient does not exist, place the message in the SERVER_LOST_DIR folder
          and consider the sending as a failure.
        - If the recipient is external, transform the message into an EmailMessage
          and use the SMTP server to relay it.

        Returns a message indicating success or failure of the operation.
        """
        dest = payload["destination"]
        user_nm = payload["sender"]
        sujet = payload["subject"]
        body = payload["content"]

        message = email.message.EmailMessage()
        dest_vl = "{nom_dossier}/{dest_}".format(nom_dossier=gloutils.SERVER_DATA_DIR, dest_=dest)
        client_soc = self._logged_users.get(user_nm)

        if client_soc:
            if not os.path.exists(dest_vl + "/email"):
                os.makedirs(dest_vl + "/email")
            with open(os.path.join(dest_vl + "/email", sujet), 'w') as f:
                f.write(json.dumps(payload))
            return gloutils.GloMessage(header=gloutils.Headers.OK)
        else:
            message["From"] = user_nm
            message["To"] = dest
            message["Subject"] = sujet
            message.set_content(body)

            try:
                with smtplib.SMTP(host=gloutils.SMTP_SERVER, timeout=10) as conc:
                    conc.send_message(message)
                return gloutils.GloMessage(header=gloutils.Headers.OK)
            except smtplib.SMTPException as e:
                return gloutils.GloMessage(header=gloutils.Headers.ERROR, payload=str(e))
            except socket.timeout:
                return gloutils.GloMessage(header=gloutils.Headers.ERROR, payload="Echec de la connexion.")

    def run(self):
        """Point d'entrée du serveur."""
        while True:
            try:
                res = select.select([self._server_socket] + self._client_socs, [], [])
                waitrs = res[0]

                for soc_c in waitrs:
                    if soc_c == self._server_socket:
                        self._accept_client()
                    else:
                        donn = glosocket.recv_msg(soc_c)
                        dico = json.loads(donn)

                        if dico["header"] == gloutils.Headers.AUTH_REGISTER:
                            glosocket.send_msg(soc_c, json.dumps(self._create_account(soc_c, dico["payload"])))
                        elif dico["header"] == gloutils.Headers.AUTH_LOGIN:
                            glosocket.send_msg(soc_c, json.dumps(self._login(soc_c, dico["payload"])))
                        elif dico["header"] == gloutils.Headers.AUTH_LOGOUT:
                            glosocket.send_msg(soc_c, json.dumps(self._logout(soc_c)))
                        elif dico["header"] == gloutils.Headers.BYE:
                            self._logout(soc_c)
                        elif dico["header"] == gloutils.Headers.INBOX_READING_REQUEST:
                            glosocket.send_msg(soc_c, json.dumps(self._get_email_list(soc_c)))
                        elif dico["header"] == gloutils.Headers.INBOX_READING_CHOICE:
                            glosocket.send_msg(soc_c, json.dumps(self._get_email(soc_c, dico["payload"])))
                        elif dico["header"] == gloutils.Headers.EMAIL_SENDING:
                            glosocket.send_msg(soc_c, json.dumps(self._send_email(dico["payload"])))
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                break
        self.cleanup()


def _main() -> int:
    server = Server()
    try:
        server.run()
    except KeyboardInterrupt:
        server.cleanup()
    return 0


if __name__ == '__main__':
    sys.exit(_main())

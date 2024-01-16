"""
"""

import argparse
import getpass
import json
import socket
import sys

import glosocket
import gloutils


class Client:
    """Client pour le serveur mail @glo2000.ca."""

    def __init__(self, destination: str) -> None:
        """
        Prépare et connecte le socket du client `_socket`.

        Prépare un attribut `_username` pour stocker le nom d'utilisateur
        courant. Laissé vide quand l'utilisateur n'est pas connecté.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((destination, gloutils.APP_PORT))
        except OSError as e:
            print(f"Error connecting to the server: {e}")
            sys.exit(1)

        self._username = ""

    def _register(self) -> None:
        """
        Demande un nom d'utilisateur et un mot de passe et les transmet au
        serveur avec l'entête `AUTH_REGISTER`.

        Si la création du compte s'est effectuée avec succès, l'attribut
        `_username` est mis à jour, sinon l'erreur est affichée.
        """

        username = input("Entrez votre nom d'utilisateur:")
        password = getpass.getpass("Entrez votre mot de passe:", None)

        message = gloutils.AuthPayload(username=username, password=password)
        data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.AUTH_REGISTER, payload=message))
        glosocket.send_msg(dest_soc=self._socket, message=data)

        data = glosocket.recv_msg(self._socket)
        header = json.loads(data)["header"]

        if header == gloutils.Headers.OK:
            self._username = username
            self.run()
        elif header == gloutils.Headers.ERROR:
            print("La création a échouée:")
            print("- Le nom d'utilisateur est invalide.")
            print("- Le mot de passe n'est pas assez sûr.")
            self.run()

    def _login(self) -> None:
        """
        Demande un nom d'utilisateur et un mot de passe et les transmet au
        serveur avec l'entête `AUTH_LOGIN`.

        Si la connexion est effectuée avec succès, l'attribut `_username`
        est mis à jour, sinon l'erreur est affichée.
        """
        username = input("Entrez votre nom d'utilisateur:")
        # password = input("Entrez votre mot de passe:")
        password = getpass.getpass("Entrez votre mot de passe:", None)

        message = gloutils.AuthPayload(username=username, password=password)
        data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.AUTH_LOGIN, payload=message))
        glosocket.send_msg(dest_soc=self._socket, message=data)

        data = glosocket.recv_msg(self._socket)
        header = json.loads(data)["header"]

        match header:
            case gloutils.Headers.OK:
                self._username = username
            case gloutils.Headers.ERROR:
                print("Nom d'utilisateur ou mot de passe invalide.")
                self.run()

    def _quit(self) -> None:
        """
        Prévient le serveur de la déconnexion avec l'entête `BYE` et ferme le
        socket du client.
        """
        try:
            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.BYE))
            glosocket.send_msg(dest_soc=self._socket, message=data)
            self._socket.close()

        except Exception as e:
            print(f"Error during client disconnect: {e}")

    def _read_email(self) -> None:
        """
        Demande au serveur la liste de ses courriels avec l'entête
        `INBOX_READING_REQUEST`.

        Affiche la liste des courriels puis transmet le choix de l'utilisateur
        avec l'entête `INBOX_READING_CHOICE`.

        Affiche le courriel à l'aide du gabarit `EMAIL_DISPLAY`.

        S'il n'y a pas de courriel à lire, l'utilisateur est averti avant de
        retourner au menu principal.
        """
        try:
            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.INBOX_READING_REQUEST))
            glosocket.send_msg(dest_soc=self._socket, message=data)

            email_list = glosocket.recv_msg(source_soc=self._socket)
            for x in email_list:
                print(x)

            selection = int(input("Selection: "))
            couriel = gloutils.EmailChoicePayload(choice=selection)

            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.INBOX_READING_CHOICE, payload=couriel))
            glosocket.send_msg(dest_soc=self._socket, message=data)

            couriel_response = glosocket.recv_msg(source_soc=self._socket)
            print(couriel_response)

        except glosocket.GLOSocketError:
            print("Error during email reading:", glosocket.GLOSocketError)

    def _send_email(self) -> None:
        """
        Demande à l'utilisateur respectivement:
        - l'adresse email du destinataire,
        - le sujet du message,
        - le corps du message.

        La saisie du corps se termine par un point seul sur une ligne.

        Transmet ces informations avec l'entête `EMAIL_SENDING`.
        """
        sender = f"{self._username}@glo2000.ca"
        destination = input("Destinataire: ")
        subject = input("Sujet: ")
        date = str(gloutils.get_current_utc_time())

        print("Corps du message: (entrez '.' sur une ligne seule pour terminer)")
        body = ""
        buffer = ""

        while buffer != ".\n":
            body += buffer
            buffer = input() + '\n'

        try:
            message = gloutils.EmailContentPayload(
                sender=sender, destination=destination, subject=subject, date=date, content=body
            )
            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.EMAIL_SENDING, payload=message))
            glosocket.send_msg(dest_soc=self._socket, message=data)

        except glosocket.GLOSocketError:
            print("Erreur lors de l'envoi du courriel:", glosocket.GLOSocketError)

    def _check_stats(self) -> None:
        """
        Demande les statistiques au serveur avec l'entête `STATS_REQUEST`.

        Affiche les statistiques à l'aide du gabarit `STATS_DISPLAY`.
        """
        count = int(input("Nombre de courriels: "))
        size = int(input("Taille du dossier: "))
        try:
            stats = gloutils.StatsPayload(count=count, size=size)
            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.STATS_REQUEST, payload=stats))
            glosocket.send_msg(dest_soc=self._socket, message=data)

        except glosocket.GLOSocketError:
            print("Erreur lors de la demande de statistiques:", glosocket.GLOSocketError)

    def _logout(self) -> None:
        """
        Préviens le serveur avec l'entête `AUTH_LOGOUT`.
        Met à jour l'attribut `_username`.
        """
        try:
            data = json.dumps(gloutils.GloMessage(header=gloutils.Headers.AUTH_LOGOUT))
            glosocket.send_msg(dest_soc=self._socket, message=data)
            self._username = ""
        except glosocket.GLOSocketError as e:
            print(f"Erreur lors de la déconnexion : {e}")

    def run(self) -> None:
        """Point d'entrée du client."""
        should_quit = False

        while not should_quit:
            if not self._username:
                print(gloutils.CLIENT_AUTH_CHOICE)
                option = input("Entrez votre choix [1-3]: ")
                match option:
                    case '1':
                        self._register()
                    case '2':
                        self._login()
                    case '3':
                        self._quit()
                    case _:
                        print("Option invalide. Veuillez choisir une option valide.")
            else:
                print(gloutils.CLIENT_USE_CHOICE)
                option = input("Entrez votre choix [1-4]: ")
                match option:
                    case '1':
                        self._read_email()
                    case '2':
                        self._send_email()
                    case '3':
                        self._check_stats()
                    case '4':
                        self._logout()
                    case _:
                        print("Option invalide. Veuillez choisir une option valide.")


def _main() -> int:
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-d", "--destination", action="store",
                            dest="dest", required=True,
                            help="Adresse IP/URL du serveur.")
        args = parser.parse_args(sys.argv[1:])

        client = Client(args.dest)
        client.run()

    except Exception as e:
        print(f"Une erreur s'est produite : {e}")

    return 0


if __name__ == '__main__':
    sys.exit(_main())

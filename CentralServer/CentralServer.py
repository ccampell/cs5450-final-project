"""
CentralServer.py
Listens to connection requests and manages interface between client and the class controlling the classification
    complexity (Classifier.py).
"""

import signal
import socket
import sys
import os
import re
import numpy as np
import sys
sys.path.append('..')
from Client.Client import Client
from ClientManager import ClientManager
from GoingDeeperClassifier import GoingDeeperClassifier

__author__ = 'Chris Campell'
__created__ = '11/29/2018'


class CentralServer:
    server_listening_port = None
    server_hostname = None
    server_listening_socket = None
    client_manager = None

    def __init__(self, server_listening_port, server_hostname, client_manager=None):
        self.server_listening_port = server_listening_port
        self.server_hostname = server_hostname
        if client_manager is not None:
            self.client_manager = client_manager
        else:
            self.client_manager = ClientManager()
        # Instantiate and start up the listening socket:
        self.server_listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_listening_socket.bind((self.server_hostname, self.server_listening_port))
        self.last_client = None
        # Param backlog=1
        # Instantiate ClassifierManager to handle classification requests:
        # self.classifier_manager = ClassifierManager()
        self.server_listening_socket.listen(1)
        print('CentralServer [Info]: The CentralServer instance is listening on port %s'
              % self.server_listening_port)
        # Primary responsibility is to accept incoming connection requests:
        self.accept_connection_requests()

    def _parse_post_message(self, msg):
        if b'.png' in msg or b'.PNG' in msg:
            header_end = msg.find(b'\x89PNG')
        elif b'.jpg' in msg:
            header_end = msg.find(b'.jpg\n') + len('.jpg\n')
        elif b'.JPG' in msg:
            header_end = msg.find(b'.JPG\n') + len('.JPG\n')
        elif b'.jpeg' in msg:
            header_end = msg.find(b'.jpeg\n') + len('.jpeg\n')
        elif b'.JPEG' in msg:
            header_end = msg.find(b'.JPEG\n') + len('.JPEG\n')
        else:
            header_end = -1
            print('CentralServer [Error]: Failed to parse the POST message sent by the client successfully.')
            exit(-1)
        msg_header = msg[0:header_end]
        img_name = msg_header[msg_header.find(b'POST\n') + len('POST\n'):-1]
        img_name = img_name.decode('utf-8')
        img_bin = msg[header_end:-2]
        return img_name, img_bin

    def accept_connection_requests(self):
        while True:
            # Accept the connection request:
            client_connection_socket, client_ip_and_port = self.server_listening_socket.accept()
            # Receive the message:
            msg = client_connection_socket.recv(1024)
            ''' Connection requests are treated specially because a client_id does not exist yet: '''
            method = msg.split()[0]
            if method.upper() == b'CONNECT':
                client_id = self._execute_connect(
                    client_hostname_or_ip=client_ip_and_port[0],
                    client_port=client_ip_and_port[1]
                )
                if client_id is None:
                    response = 'BAD\n'
                else:
                    client_id = int(client_id)
                    response = 'OK\n%d\n' % client_id
            elif method.upper() == b'POST':
                client_id = self.client_manager.get_client_id_by_hostname_or_ip_and_port(
                    client_hostname_or_ip=client_ip_and_port[0],
                    client_port=client_ip_and_port[1]
                )
                if client_id is None:
                    print('CentralServer [Error]: Received POST command from client who presumably had previously '
                          'connected. However, the client could not be identified by hostname and port.')
                    exit(-1)
                msg_all = bytearray()
                msg_all += msg
                num_segments = 1
                while True:
                    msg = client_connection_socket.recv(1024)
                    num_segments += 1
                    # print('segment: %d, %s' % (num_segments, msg))
                    if not msg:
                        # print('breaking!')
                        break
                    msg_all += msg
                    if msg_all[-2:] == b'\r\n':
                        # print('breaking!')
                        break
                msg = msg_all
                img_name, img_bin = self._parse_post_message(msg)
                response = self._execute_post(client_id=client_id, img_name=img_name, bin_img=img_bin)
            else:
                response = self.process_message(msg=msg)
            # Reply to the client with the result of the method invocation:
            client_connection_socket.send(response.encode('utf-8'))
            # Close the connection with the client:
            client_connection_socket.close()

    def __str__(self):
        return repr(self) + self.server_listening_port + self.server_hostname

    def close(self):
        self.server_listening_socket.close()

    def _execute_connect(self, client_hostname_or_ip, client_port):
        """
        _execute_connect: This method is run when the client sends a 'CONNECT\n<client-id>\n' command to the central
            server. The connected client will be registered with the server's list of clients if it doesn't already
            exist as a connected client. The OK message is sent to the client if the connection attempt was successful,
            otherwise the BAD message is sent to the client.
        :return client_id: <int> The unique identifier now associated with the client if the connection request was
            successful, else None is returned.
        """

        client_id = None
        client_manager_response = self.client_manager.add_client(
            client_hostname_or_ip=client_hostname_or_ip,
            client_port=client_port
        )
        status_code = client_manager_response.split()[0]
        if status_code.upper() == 'OK':
            client_id = client_manager_response.split()[1]
            print('CentralServer [Info]: Executed command to connect client \'%s\' successfully. '
                  'Client now registered with the CentralServer\'s ClientManager instance.' % client_id)
        return client_id

    def _execute_disconnect(self, client_id):
        """
        _execute_disconnect: This method is run when the client sends a 'DISCONNECT\n<client-id>\n' command to the
            central server. The specified client will be removed from the server's list of clients if it hasn't
            already been removed. The OK message is sent to the client if the disconnection attempt was successful,
            otherwise the BAD message is sent to the client.
        :return:
        """
        print('CentralServer [Info]: Received command to disconnect client \'%s\'. Notifying the CentralServer\'s ClientManager instance of the request.' % client_id)
        client_manager_response = self.client_manager.disconnect_client(client_id=client_id)
        print('CentralServer [Info]: Remaining Clients: %d' % len(self.client_manager.clients))
        return client_manager_response

    def _execute_post(self, client_id, img_name, bin_img):
        """
        _execute_post: This method is run when the client sends a 'POST\n<image_vector>' command to the central
            server. The specified image will be added to the list of persistent images for that client.
        :param bin_img: <bytearray> An image received from the client, still encoded as binary.
        :return:
        """
        # TODO: Remove hardcoded paths.
        if not os.path.exists('CentralServer/Images/%d' % client_id):
            os.mkdir('CentralServer/Images/%d' % client_id)
        try:
            outfile = open(('CentralServer/Images/%d/%s' % (client_id, img_name)), 'wb')
            outfile.write(bin_img)
            outfile.close()
            response = 'OK\n%s\n' % img_name
        except Exception as err:
            print('Couldn\'t save the image: \'%s\'. Encountered error: %s' % (img_name, err))
            response = 'BAD\n%s\n' % img_name
        return response

    def _execute_list_images(self, client_id):
        # TODO: remove hardcoded paths.
        if os.path.exists('CentralServer/Images/%d' % client_id):
            image_files = []
            for (dir_path, dir_names, file_names) in os.walk('CentralServer/Images/%d' % client_id):
                image_files.extend(file_names)
                break
            image_list_response = 'OK\n%d\n' % client_id
            for img in image_files:
                image_list_response = image_list_response + img + '\n'
            return image_list_response
        else:
            return 'BAD\n%d\n' % client_id

    def _execute_list_command(self, list_subcommand, client_id):
        """
        _execute_list_command: This method is run when the client sends a 'LIST\n<LIST-SUBCOMMAND>' command to the
            central server. This method determines
        :return:
        """
        if list_subcommand.upper() == b'IMAGES':
            return self._execute_list_images(client_id=client_id)

    def process_message(self, msg):
        """
        process_message: Responds to the message from the client. The received message must be defined in my protocol.
            NOTE: The CONNECT method is the only method not invoked by this helper function.
        :param msg: <bytes> The client's message to the server (binary string).
        :return response: <str> The server's response to the msg received from the client.
        """
        response = None
        # Split on white space:
        words = msg.split()
        if len(words) == 0:
            response = 'BAD\n'
            return response
        elif words[0].upper() == b'DISCONNECT' and len(words) == 2:
            client_id = int(words[1].decode('utf-8'))
            client_manager_response = self._execute_disconnect(client_id=client_id)
            return client_manager_response
        elif words[0].upper() == b'LIST' and len(words) == 3:
            subcommand = words[1]
            client_id = int(words[2].decode('utf-8'))
            # TODO: use cookie to personalize images cached by client.
            return self._execute_list_command(list_subcommand=subcommand, client_id=client_id)
        elif words[0].upper() == b'CLASSIFY' and len(words) == 3:
            client_id = int(words[1].decode('utf-8'))
            target_image_index = int(words[2].decode('utf-8'))
            print('CentralServer [Info]: Client %s requests CLASSIFY img: %s' % (client_id, target_image_index))
            clf_path = 'C:/Users/ccamp/Documents/GitHub/HerbariumDeep/frameworks/TensorFlow/TFHub/tmp/trained_model/'
            clf_label_path = 'C:/Users/ccamp/Documents/GitHub/HerbariumDeep/frameworks/TensorFlow/TFHub/tmp/output_labels.txt'
            going_deeper_classifier = GoingDeeperClassifier(clf_path, clf_label_path)
            # Get the image path:
            if os.path.exists('CentralServer/Images/%d' % client_id):
                image_files = []
                for (dir_path, dir_names, file_names) in os.walk('CentralServer/Images/%d' % client_id):
                    image_files.extend(file_names)
                    break
                labels, results = going_deeper_classifier.classify(
                    image_path=os.path.join('CentralServer/Images/%d' % client_id, image_files[target_image_index])
                )
                predicted = labels[np.argmax(results)]
                response = 'OK\n%s\n%f\n' % (predicted, np.max(results))
            else:
                response = 'BAD\nImageNotFound\n'
            return response

        else:
            response = 'BAD\n'
            return response


def handle_interrupt_signal(signal, sig_frame):
    print('CentralServer: Closing listening socket and terminating.')
    central_server.close()
    sys.exit(0)


if __name__ == '__main__':
    # Attach ctrl+c signal handler for server termination:
    signal.signal(signalnum=signal.SIGINT, handler=handle_interrupt_signal)
    # Create the listening socket for connection requests:
    server_port = 15014
    server_name = '192.168.1.87'
    central_server = CentralServer(server_listening_port=server_port, server_hostname=server_name)

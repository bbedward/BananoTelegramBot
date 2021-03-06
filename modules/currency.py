import configparser
import json
import logging
import os
import re
import datetime

import nano
import requests

from modules.conversion import BananoConversions

# Read config and parse constants
config = configparser.ConfigParser()
config.read(os.environ['MY_CONF_DIR'] + '/webhooks.ini')
logging.basicConfig(handlers=[logging.StreamHandler()], level=logging.INFO)
# Constants
WALLET = config.get('webhooks', 'wallet')
NODE_IP = config.get('webhooks', 'node_ip')

# Connect to Nano node
rpc = nano.rpc.Client(NODE_IP)


def receive_pending(sender_account):
    """
    Check to see if the account has any pending blocks and process them
    """
    try:
        logging.info("{}: in receive pending".format(datetime.datetime.utcnow()))
        pending_blocks = rpc.pending(account='{}'.format(sender_account))
        logging.info("pending blocks: {}".format(pending_blocks))
        if len(pending_blocks) > 0:
            for block in pending_blocks:
                work = get_pow(sender_account)
                if work == '':
                    logging.info("{}: processing without pow".format(
                        datetime.datetime.utcnow()))
                    receive_data = {
                        'action': "receive",
                        'wallet': WALLET,
                        'account': sender_account,
                        'block': block
                    }
                else:
                    logging.info("{}: processing with pow".format(
                        datetime.datetime.utcnow()))
                    receive_data = {
                        'action': "receive",
                        'wallet': WALLET,
                        'account': sender_account,
                        'block': block,
                        'work': work
                    }
                receive_json = json.dumps(receive_data)
                requests.post('{}'.format(NODE_IP), data=receive_json)
                logging.info("{}: block {} received".format(
                    datetime.datetime.utcnow(), block))

        else:
            logging.info('{}: No blocks to receive.'.format(datetime.datetime.utcnow()))

    except Exception as e:
        logging.info("Receive Pending Error: {}".format(e))
        raise e

    return


def get_pow(sender_account):
    """
    Retrieves the frontier (hash of previous transaction) of the provided account and generates work for the next block.
    """
    logging.info("{}: in get_pow".format(datetime.datetime.utcnow()))
    try:
        account_frontiers = rpc.accounts_frontiers([sender_account])
        frontier_hash = account_frontiers[sender_account]
    except Exception as e:
        logging.info("{}: Error checking frontier: {}".format(
            datetime.datetime.utcnow(), e))
        return ''
    logging.info("account_frontiers: {}".format(account_frontiers))

    work = ''
    logging.info("{}: hash: {}".format(datetime.datetime.utcnow(), frontier_hash))
    while work == '':
        try:
            work = rpc.work_generate(frontier_hash, use_peers=True)
            logging.info("{}: Work generated: {}".format(datetime.datetime.utcnow(), work))
        except Exception as e:
            logging.info("{}: ERROR GENERATING WORK: {}".format(
                datetime.datetime.utcnow(), e))
            pass

    return work


def send_tip(message, users_to_tip, tip_index):
    import modules.db as db
    import modules.social as social
    """
    Process tip for specified user
    """
    logging.info("{}: sending tip to {}".format(
        datetime.datetime.utcnow(), users_to_tip[tip_index]['receiver_screen_name']))
    if str(users_to_tip[tip_index]['receiver_id']) == str(
            message['sender_id']):
        self_tip_text = "Self tipping is not allowed.  Please use this bot to tip BANANO to other users!"
        social.send_reply(message, self_tip_text)

        logging.info("{}: User tried to tip themself").format(datetime.datetime.utcnow())
        return

    # Check if the receiver has an account
    try:
        user = db.User.select().where(db.User.user_id == int(users_to_tip[tip_index]['receiver_id'])).get()
        users_to_tip[tip_index]['receiver_account'] = user.account
    except db.User.DoesNotExist:
        # If they don't, create an account for them
        users_to_tip[tip_index]['receiver_account'] = rpc.account_create(
            wallet="{}".format(WALLET), work=True)
        user = db.User(
            user_id = int(users_to_tip[tip_index]['receiver_id']),
            user_name = users_to_tip[tip_index]['receiver_screen_name'],
            account = users_to_tip[tip_index]['receiver_account'],
            register=0,
            created_ts=datetime.datetime.utcnow()
        )
        user.save(force_insert=True)
        logging.info(
            "{}: Sender sent to a new receiving account.  Created  account {}".
            format(datetime.datetime.utcnow(),
                   users_to_tip[tip_index]['receiver_account']))
    # Send the tip

    message['tip_id'] = "{}{}".format(message['id'], tip_index)

    work = get_pow(message['sender_account'])
    logging.info("Sending Tip:")
    logging.info("From: {}".format(message['sender_account']))
    logging.info("To: {}".format(users_to_tip[tip_index]['receiver_account']))
    logging.info("amount: {:f}".format(message['tip_amount_raw']))
    logging.info("id: {}".format(message['tip_id']))
    logging.info("work: {}".format(work))
    if work == '':
        message['send_hash'] = rpc.send(
            wallet="{}".format(WALLET),
            source="{}".format(message['sender_account']),
            destination="{}".format(
                users_to_tip[tip_index]['receiver_account']),
            amount="{}".format(int(message['tip_amount_raw'])),
            id="tip-{}".format(message['tip_id']))
    else:
        message['send_hash'] = rpc.send(
            wallet="{}".format(WALLET),
            source="{}".format(message['sender_account']),
            destination="{}".format(
                users_to_tip[tip_index]['receiver_account']),
            amount="{}".format(int(message['tip_amount_raw'])),
            work=work,
            id="tip-{}".format(message['tip_id']))
    # Update the DB
    db.set_db_data_tip(message, users_to_tip, tip_index)

    # Get receiver's new balance
    try:
        logging.info("{}: Checking to receive new tip")
        receive_pending(users_to_tip[tip_index]['receiver_account'])
        balance_return = rpc.account_balance(
            account="{}".format(users_to_tip[tip_index]['receiver_account']))
        users_to_tip[tip_index][
            'balance'] = BananoConversions.raw_to_banano(balance_return['balance'])

        # create a string to remove scientific notation from small decimal tips
        if str(users_to_tip[tip_index]['balance'])[0] == ".":
            users_to_tip[tip_index]['balance'] = "0{}".format(
                str(users_to_tip[tip_index]['balance']))
        else:
            users_to_tip[tip_index]['balance'] = str(
                users_to_tip[tip_index]['balance'])

        # Send a DM to the receiver
        receiver_tip_text = (
            "@{0} just sent you a {1} BANANO tip! Reply to this DM with .balance to see your new balance.  If you have not "
            "registered an account, send a reply with .register to get started, or .help to see a list of "
            "commands! Learn more about BANANO at https://banano.cc"
            .format(message['sender_screen_name'], message['tip_amount_text'])) 
        social.send_dm(users_to_tip[tip_index]['receiver_id'],
                       receiver_tip_text)
    except Exception as e:
        logging.info(
            "{}: ERROR IN RECEIVING NEW TIP - POSSIBLE NEW ACCOUNT NOT REGISTERED WITH DPOW: {}"
            .format(datetime.datetime.utcnow(), e))

    logging.info("{}: tip sent to {} via hash {}".format(
        datetime.datetime.utcnow(), users_to_tip[tip_index]['receiver_screen_name'],
        message['send_hash']))

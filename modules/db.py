import configparser
import logging
import os
import datetime
from peewee import IntegerField, CharField, BigIntegerField, ForeignKeyField, DateTimeField, Model
from playhouse.pool  import PooledPostgresqlDatabase

# Read config and parse constants
config = configparser.ConfigParser()
config.read(os.environ['MY_CONF_DIR'] + '/webhooks.ini')
logging.basicConfig(handlers=[logging.StreamHandler()], level=logging.INFO)
# DB connection settings
DB_HOST = config.get('webhooks', 'host')
DB_USER = config.get('webhooks', 'user')
DB_PW = config.get('webhooks', 'password')
DB_SCHEMA = config.get('webhooks', 'schema')
DB_PORT = int(config.get('webhooks', 'port'))

database = PooledPostgresqlDatabase(DB_SCHEMA, user=DB_USER, password=DB_PW, host=DB_HOST, port=DB_PORT, max_connections=20)

class BaseModel(Model):
    class Meta:
        database = database

# Database Models
class User(BaseModel):
    user_id = IntegerField(primary_key=True)
    user_name = CharField()
    account = CharField()
    register = IntegerField()
    created_ts = DateTimeField()

    class Meta:
        db_table = 'users'

class TelegramChatMember(BaseModel):
    chat_id = BigIntegerField()
    chat_name = CharField()
    member_id = IntegerField()
    member_name = CharField()
    created_ts = DateTimeField()

    class Meta:
        db_table = 'chat_members'

class Tip(BaseModel):
    dm_id = IntegerField()
    tx_id = IntegerField()
    processed = IntegerField()
    sender = ForeignKeyField(User, backref='tips_sent')
    receiver = ForeignKeyField(User, backref='tips_received')
    dm_text = CharField()
    amount = IntegerField()
    created_ts = DateTimeField()

    class Meta:
        db_table = 'tip_list'

def create_tables():
    with database.connection_context():
        database.create_tables([User, Tip, TelegramChatMember], safe=True)

def set_db_data_tip(message, users_to_tip, t_index):
    """
    Special case to update DB information to include tip data
    """
    logging.info("{}: inserting tip into DB.".format(datetime.datetime.utcnow()))
    try:
        sender = User.select().where(User.user_id == int(message['sender_id'])).get()
        receiver = User.select().where(User.user_id == int(users_to_tip[t_index]['receiver_id'])).get()
        message_text = ' '.join(message['text']).replace('!', '').replace(
            '@', '')
        tip = Tip(dm_id=message['id'],
                tx_id=message['tip_id'],
                processed=2,
                sender=sender,
                receiver=receiver,
                dm_text=message_text,
                amount=int(message['tip_amount']),
                created_ts=datetime.datetime.utcnow())
        if tip.save(force_insert=True) == 0:
            raise Exception("Couldn't insert tip {0}".format(message['id']))
    except Exception as e:
        logging.info("{}: Exception in set_db_data_tip".format(datetime.datetime.utcnow()))
        logging.info("{}: {}".format(datetime.datetime.utcnow(), e))
        raise e

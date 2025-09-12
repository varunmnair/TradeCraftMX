from .zerodha_broker import ZerodhaBroker
from .upstox_broker import UpstoxBroker

class BrokerFactory:
    """
    Factory class to create broker instances.
    """

    @staticmethod
    def get_broker(broker_name, user_id, config):
        """
        Returns a broker instance based on the broker name.
        """
        if broker_name.lower() == 'zerodha':
            return ZerodhaBroker(
                user_id=user_id,
                api_key=config['api_key'],
                access_token=config['access_token']
            )
        elif broker_name.lower() == 'upstox':
            return UpstoxBroker(
                user_id=user_id,
                api_key=config['api_key'],
                api_secret=config['api_secret'],
                redirect_uri=config['redirect_uri'],
                code=config.get('code'),
                access_token=config.get('access_token')
            )
        else:
            raise ValueError(f"Broker '{broker_name}' is not supported.")
# -*- coding: utf-8 -*-
import json
import socket
import time
from typing import Optional, Union, Any
import logging
from .utils import get_pid_list, get_sn
import threading

CMD_INFO = 0
CMD_QUERY = 2
CMD_SET = 3
CMD_LIST = [CMD_INFO, CMD_QUERY, CMD_SET]
_LOGGER = logging.getLogger(__name__)


class tcp_client(object):
    """
    Represents a device
    """
    # FIX: Use actual defaults/type hints, not Python class type objects
    _ip: str = ""
    _port: int = 5555
    _connect: Optional[socket.socket] = None
    
    _device_id: str = ""
    _pid: str = ""
    _device_type_code: str = ""
    _icon: str = ""
    _device_model_name: str = ""
    _dpid: list = []
    _sn: str = ""
    
    def __init__(self, ip):
        self._ip = ip
        self._connect = None 
        self._is_reconnecting = False
        self._close_connection() 
        
        # FIX: Try to connect synchronously ONCE during setup to get device_id
        self._initial_connect()
    
    def _initial_connect(self):
        """Synchronous connection for initial setup so device metadata is populated."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self._ip, self._port))
            self._connect = s
            self._device_info()
        except Exception as e:
            _LOGGER.error(f'Initial connection failed for {self._ip}: {e}')
            self._close_connection()
            # If initial connection fails, fallback to background retries
            self._reconnect()

    def _close_connection(self):
        if self._connect:
            try:
                self._connect.close()
            except Exception as e:
                _LOGGER.error(f'Error while closing the connection: {e}')
            self._connect = None
        
    def _reconnect(self):
        # Prevent spawning multiple reconnect threads at once
        if getattr(self, '_is_reconnecting', False):
            return
            
        self._is_reconnecting = True

        def reconnect_thread():            
            while True:
                try:
                    self._close_connection() # Ensure socket is clean before retrying
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3)
                    s.connect((self._ip, self._port))
                    self._connect = s
                    self._device_info()
                    self._is_reconnecting = False
                    _LOGGER.info(f'Successfully reconnected to {self._ip}')
                    return
                except Exception as e:
                    _LOGGER.info(f'Reconnection failed for {self._ip}: {e}')
                    time.sleep(10)  # Wait 10 seconds

        thread = threading.Thread(target=reconnect_thread)
        thread.daemon = True  
        thread.start()


    @property
    def check(self) -> bool:
        return True
    
    @property
    def dpid(self):
        return self._dpid
    
    @property
    def device_model_name(self):
        return self._device_model_name
    
    @property
    def icon(self):
        return self._icon
    
    @property
    def device_type_code(self) -> str:
        return self._device_type_code
    
    @property
    def device_id(self):
        return self._device_id
    
    def _device_info(self) -> None:
        """
        get info for device model
        """
        self._only_send(CMD_INFO, {})
        try:
            resp = self._connect.recv(1024)
            resp_json = json.loads(resp.strip())            
        except:
            _LOGGER.info('_device_info.recv.error')
            return None
        
        if resp_json.get('msg') is None or type(resp_json['msg']) is not dict:
            _LOGGER.info('_device_info.recv.error1')
            return None
        
        if resp_json['msg'].get('did') is None:
            _LOGGER.info('_device_info.recv.error2')
            return None

        self._device_id = resp_json['msg']['did']
        
        if resp_json['msg'].get('pid') is None:
            _LOGGER.info('_device_info.recv.error3')
            return None
        
        self._pid = resp_json['msg']['pid']        
        pid_list = get_pid_list()

        for item in pid_list:
            match = False
            for item1 in item['m']:
                if item1['pid'] == self._pid:
                    match = True
                    self._icon = item1['i']
                    self._device_model_name = item1['n']
                    self._dpid = item1['dpid']
                    break
            
            if match:
                self._device_type_code = item['c']                
                break
        
        _LOGGER.info(f"Loaded Info: {self._device_id}, {self._device_type_code}, {self._pid}")
    
    def _get_package(self, cmd: int, payload: dict) -> bytes:
        self._sn = get_sn()
        if CMD_SET == cmd:
            message = {
                'pv': 0, 'cmd': cmd, 'sn': self._sn,
                'msg': {'attr': [int(item) for item in payload.keys()], 'data': payload}
            }
        elif CMD_QUERY == cmd:
            message = {'pv': 0, 'cmd': cmd, 'sn': self._sn, 'msg': {'attr': [0]}}
        elif CMD_INFO == cmd:
            message = {'pv': 0, 'cmd': cmd, 'sn': self._sn, 'msg': {}}
        else:
            raise Exception('CMD is not valid')
        
        payload_str = json.dumps(message, separators=(',', ':',))
        return bytes(payload_str + "\r\n", encoding='utf8')
    
    def _send_receiver(self, cmd: int, payload: dict) -> Union[dict, Any]:
        if not self._connect:
            _LOGGER.warning("Connection is currently down. Initiating reconnect.")
            self._reconnect()
            return {}

        try:
            self._connect.send(self._get_package(cmd, payload))
        except Exception as e:
            _LOGGER.error(f'Send error in _send_receiver: {e}')
            self._close_connection()
            self._reconnect()
            return {}

        try:
            i = 10
            while i > 0:
                res = self._connect.recv(1024)
                i -= 1
                if self._sn in str(res):
                    payload = json.loads(res.strip())
                    if not payload or len(payload) == 0: return {}
                    if payload.get('msg') is None or type(payload['msg']) is not dict: return {}
                    if payload['msg'].get('data') is None or type(payload['msg']['data']) is not dict: return {}
                    return payload['msg']['data']
            return {}

        except Exception as e:
            _LOGGER.info(f'_send_receiver.recv.error: {e}')
            self._close_connection()
            self._reconnect()  
            return {}
    
    def _only_send(self, cmd: int, payload: dict) -> None:
        if not self._connect:
            _LOGGER.warning("Connection is currently down. Initiating reconnect.")
            self._reconnect()
            return
            
        try:
            self._connect.send(self._get_package(cmd, payload))
        except Exception as e:
            _LOGGER.error(f'_only_send error: {e}')
            self._close_connection()
            self._reconnect()
    
    def control(self, payload: dict) -> bool:
        self._only_send(CMD_SET, payload)
        return True
    
    def query(self) -> dict:
        return self._send_receiver(CMD_QUERY, {})

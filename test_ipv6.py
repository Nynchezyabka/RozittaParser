import socket

socket.setdefaulttimeout(5)
try:
    socket.getaddrinfo('api.telegram.org', 443, socket.AF_INET6)
    print('✅ IPv6 работает отлично')
except Exception as e:
    print(f'❌ IPv6 зависает или не работает: {e}')
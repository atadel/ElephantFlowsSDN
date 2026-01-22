from scapy.all import send, IP, UDP, TCP, Raw
from scapy.all import get_if_list, get_if_addr
import time
import sys
import random

def get_my_ip():
    for iface in get_if_list():
        if iface != "lo":
            try:
                ip = get_if_addr(iface)
                if ip != "0.0.0.0":
                    return ip
            except:
                pass
    return "0.0.0.0"

my_ip = get_my_ip()

##### MOŻLIWE HOSTY ######
HOST_IPS = ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5', '10.0.0.6']

# Zakres portów dla różnych typów ruchu
PORT_RANGE_MOUSE_UDP = range(5000, 5010)  # Mały ruch, wrażliwy na opóźnienia (Myszy)
PORT_RANGE_ELEPHANT_UDP = range(6000, 6010) # Duży, agresywny ruch (Słonie)

# Szansa wylosowania słonia
ELEPHANT_PROBABILITY = 0.15 # 15% szans 

##### PRZEPŁYWY 
# Mysz (Mouse Flow)
MOUSE_PACKET_SIZE = 50 #pakietów 1-bajtowych
MOUSE_INTERVAL_SEC = 0.2  # Wysyłaj co 200ms

# Słoń (Elephant Flow)
ELEPHANT_PACKET_SIZE = 1400 #pakietów 1-bajtowych
ELEPHANT_DURATION_SEC = 45 # Słoń trwa 5 sekund
PACKET_COUNT = 60 #ile pakietów wysyłamy na raz funkcją send 

#my_ip = sys.argv[1] #skąd generujemy

def generate_elephant(src_ip, dest_ip):
    """Generuje agresywny, czasowy przepływ Słonia."""
    counter =0 
    throughput =0 
    port = random.choice(PORT_RANGE_ELEPHANT_UDP)
    payload = 'E' * ELEPHANT_PACKET_SIZE 
    
    print(f"[{my_ip}] START Elephant -> {dest_ip}:{port} przez {ELEPHANT_DURATION_SEC}s")
    
    #packet - default packet class 
    # kazdy slash to nowa warstwa 
    # kazda warstwa przyjmuje argumenty 
    packet = IP(dst=dest_ip) / UDP(sport=random.randint(40000, 50000), dport=port) / payload #sport, dport - source, destination
    packet_size = len(packet)

    start_time = time.time()
    while time.time() - start_time < ELEPHANT_DURATION_SEC: #funkcja działa przez 5 sekund
        send(packet, count=PACKET_COUNT, verbose=0)
        #time.sleep(0.001) 
        counter += PACKET_COUNT
    czas = time.time() - start_time
    throughput = (counter*packet_size*8)/(czas*1000000)

    print(f"[{my_ip}] STOP Elephant -> {dest_ip}:{port}")
    print(f"Throughput: {throughput} Mbps, czas: {czas}")



def generate_mouse(src_ip, dest_ip):
    port = random.choice(PORT_RANGE_MOUSE_UDP)
    payload = 'M' * MOUSE_PACKET_SIZE
    packet = IP(dst=dest_ip) / UDP(sport=random.randint(30000, 40000), dport=port) / payload
    send(packet, count=1, verbose=0)
    print(f"[{my_ip}] Sent Mice -> {dest_ip}:{port}") # Opcjonalne logowanie
    

def main():
    src_ip = "10.0.0.1"
    #wybór celu 
    #src_ips = [ip for ip in HOST_IPS]
    #src_ip = random.choice(src_ips)
    possible_destinations = [ip for ip in HOST_IPS if ip != my_ip]
    dest_ip = random.choice(possible_destinations)
 
    #wybór typu pakietu
    if random.random() < ELEPHANT_PROBABILITY:
        # Generuj Słonia i czekaj aż się zakończy
        generate_elephant(src_ip, dest_ip)
    else:
        # Generuj pojedynczy pakiet Myszy
        generate_mouse(src_ip, dest_ip)

    #czas oczekiwania
    wait_time = random.uniform(MOUSE_INTERVAL_SEC, MOUSE_INTERVAL_SEC + 0.5) #dolny, górny zakres
    time.sleep(wait_time)

if __name__ == '__main__':
    main()

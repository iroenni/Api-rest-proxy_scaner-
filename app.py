from flask import Flask, jsonify
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from flask_cors import CORS  # Opcional para frontends

app = Flask(__name__)
CORS(app)  # Solo necesario si usas frontend

# Configuración
CACHE_EXPIRATION_MINUTES = 30
TEST_URL = "https://httpbin.org/ip"
REQUEST_TIMEOUT = 10

# Cache para almacenar proxies
proxy_cache = {
    'proxies': [],
    'last_updated': None,
    'expires_in': timedelta(minutes=CACHE_EXPIRATION_MINUTES)
}

def fetch_proxies_from_source(url, parser_type):
    """Obtiene proxies de una fuente específica"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        proxies = []
        
        if parser_type == 'table':
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')[1:20]  # Limitar a 20 proxies por fuente
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        ip = cols[0].text.strip()
                        port = cols[1].text.strip()
                        protocol = 'https' if 'ssl' in url else 'http'
                        proxies.append({
                            'ip': ip,
                            'port': port,
                            'protocol': protocol,
                            'source': url,
                            'last_checked': None,
                            'working': None
                        })
        return proxies
    except Exception as e:
        print(f"Error fetching from {url}: {str(e)}")
        return []

def test_proxy(proxy):
    """Verifica si un proxy funciona"""
    try:
        proxy_url = f"{proxy['protocol']}://{proxy['ip']}:{proxy['port']}"
        response = requests.get(
            TEST_URL,
            proxies={
                'http': proxy_url,
                'https': proxy_url
            },
            timeout=REQUEST_TIMEOUT
        )
        if response.status_code == 200:
            proxy['last_checked'] = datetime.now().isoformat()
            proxy['working'] = True
            return proxy
    except Exception as e:
        print(f"Proxy {proxy['ip']}:{proxy['port']} failed: {str(e)}")
    
    return None

def update_proxy_cache():
    """Actualiza la caché de proxies"""
    print("Actualizando caché de proxies...")
    
    sources = [
        {'url': 'https://www.sslproxies.org/', 'parser': 'table'},
        {'url': 'https://free-proxy-list.net/', 'parser': 'table'},
        {'url': 'https://hidemy.name/es/proxy-list/', 'parser': 'table'},
        {'url': 'https://proxyscrape.com/free-proxy-list', 'parser': 'table'}
    ]
    
    all_proxies = []
    
    # Obtener proxies de todas las fuentes
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for source in sources:
            futures.append(executor.submit(
                fetch_proxies_from_source, 
                source['url'], 
                source['parser']
            ))
        
        for future in futures:
            all_proxies.extend(future.result())
    
    # Eliminar duplicados
    unique_proxies = []
    seen = set()
    for proxy in all_proxies:
        identifier = f"{proxy['ip']}:{proxy['port']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_proxies.append(proxy)
    
    # Verificar proxies (usando más hilos para mayor velocidad)
    working_proxies = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(test_proxy, unique_proxies)
        for result in results:
            if result:
                working_proxies.append(result)
    
    # Actualizar caché
    proxy_cache['proxies'] = working_proxies
    proxy_cache['last_updated'] = datetime.now()
    print(f"Caché actualizada con {len(working_proxies)} proxies funcionales")

@app.route('/')
def home():
    """Endpoint de bienvenida"""
    return jsonify({
        'message': 'Bienvenido a la API de Proxy Generator',
        'endpoints': {
            '/proxies': 'Obtener todos los proxies',
            '/proxies/<protocol>': 'Filtrar por protocolo (http/https)',
            '/stats': 'Estadísticas de los proxies'
        },
        'documentation': 'https://github.com/tu-usuario/proxy-generator-api'
    })

@app.route("/proxies", methods=["GET"])
def get_proxies():
    """Devuelve todos los proxies verificados"""
    if (not proxy_cache['proxies'] or 
        datetime.now() > proxy_cache['last_updated'] + proxy_cache['expires_in']):
        update_proxy_cache()
    
    return jsonify({
        'count': len(proxy_cache['proxies']),
        'last_updated': proxy_cache['last_updated'].isoformat(),
        'proxies': proxy_cache['proxies']
    })

@app.route("/proxies/<protocol>", methods=["GET"])
def get_proxies_by_protocol(protocol):
    """Filtra proxies por protocolo (http/https)"""
    if protocol not in ['http', 'https']:
        return jsonify({'error': 'Protocolo no válido. Use http o https'}), 400
    
    if (not proxy_cache['proxies'] or 
        datetime.now() > proxy_cache['last_updated'] + proxy_cache['expires_in']):
        update_proxy_cache()
    
    filtered = [p for p in proxy_cache['proxies'] if p['protocol'] == protocol]
    
    return jsonify({
        'count': len(filtered),
        'protocol': protocol,
        'proxies': filtered
    })

@app.route("/stats", methods=["GET"])
def get_stats():
    """Estadísticas de los proxies"""
    if not proxy_cache['proxies']:
        update_proxy_cache()
    
    http_count = sum(1 for p in proxy_cache['proxies'] if p['protocol'] == 'http')
    https_count = len(proxy_cache['proxies']) - http_count
    
    sources = {}
    for proxy in proxy_cache['proxies']:
        domain = proxy['source'].split('/')[2]
        sources[domain] = sources.get(domain, 0) + 1
    
    return jsonify({
        'total_proxies': len(proxy_cache['proxies']),
        'http_proxies': http_count,
        'https_proxies': https_count,
        'sources': sources,
        'last_updated': proxy_cache['last_updated'].isoformat()
    })

if __name__ == "__main__":
    # Cargar caché al iniciar
    update_proxy_cache()
    
    # Configuración para Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
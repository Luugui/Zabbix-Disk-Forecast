import streamlit as st
import pandas as pd
from pyzabbix import ZabbixAPI

# --- Configuração da Página Streamlit ---
st.set_page_config(
    page_title="Zabbix Disk Forecast",
    page_icon="💾",
    layout="wide"
)

st.title('💾 Previsão de Espaço em Disco para o Zabbix')
st.markdown("""
Esta ferramenta se conecta à API do Zabbix para analisar os itens monitorados e estimar o espaço em disco que será consumido pelo armazenamento de histórico e tendências. 
**Atenção:** Os valores são **estimativas** e não incluem o overhead do banco de dados (índices, fragmentação, etc.).
""")

# --- Estimativas de Tamanho (em bytes) ---
# (As mesmas do script original)
ESTIMATED_BYTES_PER_VALUE = {
    0: 50,  # Numeric (float)
    1: 256, # Character
    2: 512, # Log
    3: 50,  # Numeric (unsigned)
    4: 512, # Text
}
ESTIMATED_BYTES_PER_TREND = 128

# --- Funções Auxiliares ---
# (As mesmas do script original, sem alterações)
def parse_zabbix_time(time_str):
    """Converte strings de tempo do Zabbix (30s, 1m, 2h, 7d) para segundos."""
    if not isinstance(time_str, str) or not time_str:
        return 0
    unit = time_str[-1:].lower()
    try:
        value = int(time_str[:-1])
    except (ValueError, TypeError):
        try:
            return int(time_str)
        except (ValueError, TypeError):
            return 0
    if unit == 's': return value
    if unit == 'm': return value * 60
    if unit == 'h': return value * 3600
    if unit == 'd': return value * 86400
    if unit == 'w': return value * 604800
    return 0

def format_bytes(byte_count):
    """Formata bytes em um formato legível (KB, MB, GB)."""
    if byte_count is None or byte_count == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels):
        byte_count /= power
        n += 1
    return f"{byte_count:.2f} {power_labels[n]}B"

# --- Lógica Principal em Cache ---
@st.cache_data(ttl=600) # Adiciona cache para não sobrecarregar a API
def fetch_and_process_zabbix_data(server, user, password):
    """Função principal que busca e processa os dados, agora com cache."""
    try:
        zapi = ZabbixAPI(server)
        # zapi.session.verify = False # Descomente se usar SSL auto-assinado
        zapi.login(user, password)
    except Exception as e:
        # Retorna uma tupla indicando o erro
        return (None, f"Erro ao conectar na API do Zabbix: {e}")

    items = zapi.item.get(
        output=['name', 'key_', 'delay', 'history', 'trends', 'value_type'],
        selectHosts=['host'],
        monitored=True
    )
    zapi.user.logout()

    results_list = []
    total_history_size = 0
    total_trends_size = 0

    for item in items:
        delay_seconds = parse_zabbix_time(item['delay'])
        history_seconds = parse_zabbix_time(item['history'])
        trends_seconds = parse_zabbix_time(item['trends'])

        item_history_size = 0
        if delay_seconds > 0 and history_seconds > 0:
            total_values = (history_seconds / delay_seconds)
            value_type = int(item['value_type'])
            bytes_per_value = ESTIMATED_BYTES_PER_VALUE.get(value_type, 50)
            item_history_size = total_values * bytes_per_value
        
        item_trends_size = 0
        if trends_seconds > 0:
            total_trend_hours = trends_seconds / 3600
            item_trends_size = total_trend_hours * ESTIMATED_BYTES_PER_TREND

        total_history_size += item_history_size
        total_trends_size += item_trends_size
        item_total_size = item_history_size + item_trends_size
        
        results_list.append({
            "Host": item['hosts'][0]['host'],
            "Item": item['name'],
            "Intervalo": item['delay'],
            "Retenção Histórico": item['history'],
            "Retenção Tendências": item['trends'],
            "Est. Histórico": item_history_size,
            "Est. Tendências": item_trends_size,
            "Total Item": item_total_size,
        })
    
    summary = {
        "total_items": len(items),
        "total_history_size": total_history_size,
        "total_trends_size": total_trends_size,
        "grand_total_size": total_history_size + total_trends_size
    }
    
    # Retorna os resultados e o resumo. O segundo elemento da tupla é None se não houver erro.
    return (results_list, summary, None)


# --- Interface do Usuário (Sidebar) ---
st.sidebar.header('Configurações da API do Zabbix')
zabbix_server = st.sidebar.text_input(
    'URL do Servidor Zabbix', 
    'https://zabbix.seu_dominio.com'
)
zabbix_user = st.sidebar.text_input('Usuário da API', 'Admin')
zabbix_password = st.sidebar.text_input('Senha da API', type='password')

if st.sidebar.button('📊 Analisar Zabbix'):
    if not zabbix_server or not zabbix_user or not zabbix_password:
        st.warning('Por favor, preencha todos os campos de configuração da API.')
    else:
        with st.spinner('Conectando à API do Zabbix e buscando itens... Isso pode levar alguns minutos.'):
            results, summary, error = fetch_and_process_zabbix_data(zabbix_server, zabbix_user, zabbix_password)

        if error:
            st.error(error)
        else:
            st.header('Resumo Geral da Previsão')
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Estimado", format_bytes(summary['grand_total_size']))
            col2.metric("Total Histórico", format_bytes(summary['total_history_size']))
            col3.metric("Total Tendências", format_bytes(summary['total_trends_size']))
            col4.metric("Itens Analisados", f"{summary['total_items']:,}")

            st.header('Detalhes por Item')
            
            df = pd.DataFrame(results)

            # Formata as colunas de tamanho para exibição
            df_display = df.copy()
            df_display['Est. Histórico'] = df['Est. Histórico'].apply(format_bytes)
            df_display['Est. Tendências'] = df['Est. Tendências'].apply(format_bytes)
            df_display['Total Item'] = df['Total Item'].apply(format_bytes)

            st.dataframe(
                df_display,
                width='stretch',
                hide_index=True,
            )
            
            # Adiciona a opção de download em CSV
            @st.cache_data
            def convert_df_to_csv(df_to_convert):
                return df_to_convert.to_csv(index=False).encode('utf-8')

            csv = convert_df_to_csv(df)
            st.download_button(
                label="📥 Baixar dados como CSV",
                data=csv,
                file_name='zabbix_disk_forecast.csv',
                mime='text/csv',
            )
else:
    st.info('Preencha os dados de conexão na barra lateral e clique em "Analisar Zabbix" para começar.')

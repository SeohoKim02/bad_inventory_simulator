
import json
import streamlit as st
import streamlit.components.v1 as components


def _records_json(df):
    return df.to_json(orient="records", force_ascii=False)


def create_kakao_map_html(stores, routes, kakao_js_key, highlight_paths=None):
    stores_data = stores.copy().dropna(subset=["latitude", "longitude"])
    routes_data = routes.copy()
    highlight_paths = highlight_paths or []

    if stores_data.empty:
        return "<p>지도에 표시할 위치 데이터가 없습니다.</p>"

    kakao_js_key = str(kakao_js_key).strip()

    center_lat = float(stores_data["latitude"].mean())
    center_lng = float(stores_data["longitude"].mean())

    stores_json = _records_json(stores_data)
    routes_json = _records_json(routes_data)
    highlight_paths_json = json.dumps(highlight_paths, ensure_ascii=False)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
        <style>
            html, body { margin: 0; padding: 0; width: 100%; height: 100%; font-family: Arial, sans-serif; }
            #map { width: 100%; height: 650px; border-radius: 14px; border: 1px solid #dddddd; }
        </style>
    </head>
    <body>
        <div id="map"></div>
        <script>
            var stores = __STORES_JSON__;
            var routes = __ROUTES_JSON__;
            var highlightPaths = __HIGHLIGHT_PATHS_JSON__;

            var script = document.createElement('script');
            script.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=__KAKAO_KEY__&autoload=false';
            script.onload = function() { kakao.maps.load(function() { initMap(); }); };
            document.head.appendChild(script);

            function initMap() {
                var mapContainer = document.getElementById('map');
                var mapOption = {
                    center: new kakao.maps.LatLng(__CENTER_LAT__, __CENTER_LNG__),
                    level: 8
                };

                var map = new kakao.maps.Map(mapContainer, mapOption);
                var storeById = {};
                var storeByName = {};
                var bounds = new kakao.maps.LatLngBounds();

                stores.forEach(function(store) {
                    if (store.latitude == null || store.longitude == null) return;

                    var position = new kakao.maps.LatLng(store.latitude, store.longitude);
                    storeById[String(store.store_id)] = store;
                    storeByName[String(store.store_name)] = store;
                    bounds.extend(position);

                    var marker = new kakao.maps.Marker({ map: map, position: position });
                    var storeName = store.store_name || "점포";
                    var storeType = store.type || "unknown";

                    var info = new kakao.maps.InfoWindow({
                        content:
                            '<div style="padding:10px 14px;font-size:15px;white-space:nowrap;">' +
                            '<b>' + storeName + '</b><br>' +
                            '유형: <b>' + storeType + '</b>' +
                            '</div>'
                    });

                    kakao.maps.event.addListener(marker, 'mouseover', function() { info.open(map, marker); });
                    kakao.maps.event.addListener(marker, 'mouseout', function() { info.close(); });
                });

                if (stores.length > 0) map.setBounds(bounds);

                routes.slice(0, 400).forEach(function(route) {
                    var fromStore = storeById[String(route.from_id)];
                    var toStore = storeById[String(route.to_id)];
                    if (!fromStore || !toStore) return;

                    var path = [
                        new kakao.maps.LatLng(fromStore.latitude, fromStore.longitude),
                        new kakao.maps.LatLng(toStore.latitude, toStore.longitude)
                    ];

                    var polyline = new kakao.maps.Polyline({
                        path: path,
                        strokeWeight: 1,
                        strokeColor: '#C9CDD2',
                        strokeOpacity: 0.18,
                        strokeStyle: 'solid'
                    });

                    polyline.setMap(map);
                });

                highlightPaths.forEach(function(pathInfo, idx) {
                    var pathNames = pathInfo.path_names || [];
                    var label = pathInfo.label || "추천 경로";
                    var coords = [];

                    pathNames.forEach(function(name) {
                        var store = storeByName[String(name)];
                        if (store) coords.push(new kakao.maps.LatLng(store.latitude, store.longitude));
                    });

                    if (coords.length < 2) return;

                    var highlightLine = new kakao.maps.Polyline({
                        path: coords,
                        strokeWeight: 2,
                        strokeColor: '#F59F00',
                        strokeOpacity: 0.45,
                        strokeStyle: 'solid'
                    });

                    highlightLine.setMap(map);

                    var info = new kakao.maps.InfoWindow({
                        content:
                            '<div style="padding:8px;font-size:13px;white-space:nowrap;background:#FFF8CC;">' +
                            '<b>' + label + '</b>' +
                            '</div>'
                    });

                    kakao.maps.event.addListener(highlightLine, 'mouseover', function(mouseEvent) {
                        info.setPosition(mouseEvent.latLng);
                        info.open(map);
                    });

                    kakao.maps.event.addListener(highlightLine, 'mouseout', function() { info.close(); });
                });
            }
        </script>
    </body>
    </html>
    """

    html = html.replace("__KAKAO_KEY__", kakao_js_key)
    html = html.replace("__CENTER_LAT__", str(center_lat))
    html = html.replace("__CENTER_LNG__", str(center_lng))
    html = html.replace("__STORES_JSON__", stores_json)
    html = html.replace("__ROUTES_JSON__", routes_json)
    html = html.replace("__HIGHLIGHT_PATHS_JSON__", highlight_paths_json)

    return html


def show_kakao_map(stores, routes, kakao_js_key):
    html = create_kakao_map_html(stores, routes, kakao_js_key)
    st.iframe(html, height=720, width="stretch")


def show_kakao_map_with_highlights(stores, routes, kakao_js_key, highlight_paths):
    html = create_kakao_map_html(stores, routes, kakao_js_key, highlight_paths)
    st.iframe(html, height=720, width="stretch")


def show_kakao_map_with_multi_trucks(
    stores,
    routes,
    kakao_js_key,
    truck_scenarios,
    speed_multiplier=1.0,
    default_selected_count=3,
):
    stores_data = stores.copy().dropna(subset=["latitude", "longitude"])
    routes_data = routes.copy()

    if stores_data.empty:
        st.iframe("<p>지도에 표시할 위치 데이터가 없습니다.</p>", height=200, width="stretch")
        return

    kakao_js_key = str(kakao_js_key).strip()
    speed_multiplier = float(speed_multiplier)
    truck_scenarios = truck_scenarios or []
    default_selected_count = int(default_selected_count)

    center_lat = float(stores_data["latitude"].mean())
    center_lng = float(stores_data["longitude"].mean())

    stores_json = _records_json(stores_data)
    routes_json = _records_json(routes_data)
    scenarios_json = json.dumps(truck_scenarios, ensure_ascii=False)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">

        <style>
            html, body {
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                font-family: Arial, sans-serif;
                color: #222;
            }

            #map {
                width: 100%;
                height: 590px;
                border-radius: 16px;
                border: 1px solid #dddddd;
            }

            #control-panel {
                margin-top: 12px;
                padding: 14px 16px;
                border: 1px solid #eadfba;
                border-radius: 16px;
                background: linear-gradient(135deg, #fffbea, #fff3bf);
                font-size: 15px;
            }

            #route-panel {
                margin-top: 14px;
                padding: 18px;
                border: 1px solid #e5e5e5;
                border-radius: 18px;
                background: #ffffff;
                box-shadow: 0 4px 14px rgba(0,0,0,0.06);
            }

            .truck-marker {
                min-width: 48px;
                height: 48px;
                padding: 0 9px;
                display: flex;
                gap: 3px;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                background: #fff3bf;
                border: 4px solid #ffd43b;
                box-shadow: 0 4px 12px rgba(0,0,0,0.28);
                font-size: 24px;
                font-weight: 900;
                transform: translate(-24px, -24px);
                white-space: nowrap;
            }

            .panel-title {
                font-size: 21px;
                font-weight: 900;
                margin-bottom: 12px;
            }

            .route-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                gap: 12px;
                margin-bottom: 14px;
            }

            .route-mini {
                border-radius: 14px;
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                padding: 12px;
            }

            .route-label {
                font-size: 12px;
                color: #777;
                margin-bottom: 4px;
            }

            .route-value {
                font-size: 16px;
                font-weight: 900;
            }

            .reason-box {
                padding: 12px 14px;
                background: #fffbea;
                border: 1px solid #ffe066;
                border-radius: 14px;
                line-height: 1.6;
                margin-bottom: 14px;
            }

            .inventory-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 12px;
                margin-top: 10px;
            }

            .inventory-card {
                border: 1px solid #e9ecef;
                border-radius: 16px;
                padding: 14px;
                background: #fafafa;
            }

            .store-name {
                font-size: 17px;
                font-weight: 900;
                margin-bottom: 4px;
            }

            .store-role {
                color: #666;
                font-size: 13px;
                margin-bottom: 10px;
            }

            .bar-label {
                display: flex;
                justify-content: space-between;
                font-size: 13px;
                margin-bottom: 5px;
                color: #555;
            }

            .bar-track {
                width: 100%;
                height: 14px;
                border-radius: 999px;
                background: #e9ecef;
                overflow: hidden;
                margin-bottom: 9px;
            }

            .bar-before {
                height: 100%;
                background: #adb5bd;
                border-radius: 999px;
            }

            .bar-after {
                height: 100%;
                background: #228be6;
                border-radius: 999px;
            }

            .change-plus { color: #2b8a3e; font-weight: 900; }
            .change-minus { color: #c92a2a; font-weight: 900; }

            button {
                padding: 8px 12px;
                margin-right: 6px;
                margin-top: 4px;
                border: 1px solid #ddd;
                border-radius: 10px;
                background: white;
                cursor: pointer;
                font-weight: 700;
            }

            button:hover { background: #fff3bf; }

            .candidate-selector {
                margin-top: 12px;
                padding: 10px 12px;
                background: rgba(255,255,255,0.72);
                border: 1px solid rgba(255,255,255,0.9);
                border-radius: 14px;
            }

            .candidate-title {
                font-size: 14px;
                font-weight: 900;
                margin-bottom: 8px;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
            }

            .candidate-title:hover {
                color: #0b5ed7;
            }

            .candidate-title-left {
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }

            .candidate-toggle-icon {
                font-size: 13px;
                color: #555;
            }

            .candidate-list {
                display: none;
                margin-top: 8px;
            }

            .candidate-list.open {
                display: block;
            }

            .candidate-item {
                display: flex;
                align-items: flex-start;
                gap: 7px;
                padding: 7px 8px;
                margin: 5px 0;
                background: #ffffff;
                border: 1px solid #f1e5b8;
                border-radius: 10px;
                cursor: pointer;
                font-size: 13px;
                line-height: 1.35;
            }

            .candidate-item:hover {
                background: #fff8db;
            }

            .candidate-item input {
                margin-top: 2px;
                cursor: pointer;
            }

            .candidate-rank {
                font-weight: 900;
                color: #f08c00;
            }

            .click-guide {
                margin-top: 8px;
                color: #555;
                font-size: 13px;
                line-height: 1.5;
            }

            .selected-list {
                margin-top: 8px;
                padding: 8px 10px;
                background: rgba(255,255,255,0.65);
                border: 1px solid rgba(255,255,255,0.8);
                border-radius: 12px;
                font-size: 13px;
                line-height: 1.5;
            }
        </style>
    </head>

    <body>
        <div id="map"></div>

        <div id="control-panel">
            <b>🚚 지도 클릭 기반 재고 이동 시뮬레이션</b><br>
            상태: <span id="truck-status">준비 중</span><br>
            현재 배속: <b><span id="speed-text">__SPEED__</span>x</b> /
            전체 후보 경로 수: <b><span id="route-count">0</span>개</b> /
            선택 경로 수: <b><span id="selected-count">0</span>개</b>

            <div id="candidate-selector" class="candidate-selector"></div>

            <div style="margin-top:10px;">
                <button onclick="restart이동수단s()">선택 경로 재고 이동 재생</button>
                <button onclick="selectAllRoutes()">전체 경로 선택</button>
                <button onclick="clearSelectedRoutes()">선택 해제</button>
                <button onclick="pause이동수단s()">일시정지</button>
                <button onclick="resume이동수단s()">다시 재생</button>
            </div>
            <div id="selected-list" class="selected-list">선택된 경로가 없습니다.</div>
        </div>

        <div id="route-panel"></div>

        <script>
            var stores = __STORES_JSON__;
            var routes = __ROUTES_JSON__;
            var scenarios = __SCENARIOS_JSON__;
            var speedMultiplier = Number(__SPEED__);
            var defaultSelectedCount = Number(__DEFAULT_SELECTED_COUNT__);

            var map = null;
            var storeById = {};
            var storeByName = {};
            var routeStates = [];
            var truckStates = [];
            var animationTimer = null;
            var isPaused = false;
            var selectedIndexes = {};
            var lastClickedIndex = null;

            var colors = ['#FFD43B', '#228BE6', '#51CF66', '#FF922B', '#CC5DE8', '#20C997', '#FF6B6B', '#748FFC', '#F06595', '#845EF7'];

            var script = document.createElement('script');
            script.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=__KAKAO_KEY__&autoload=false';

            script.onload = function() {
                kakao.maps.load(function() {
                    initMap();
                });
            };

            script.onerror = function() {
                document.getElementById('truck-status').innerHTML = '카카오 SDK 로드 실패';
            };

            document.head.appendChild(script);

            function initMap() {
                var mapContainer = document.getElementById('map');
                var mapOption = {
                    center: new kakao.maps.LatLng(__CENTER_LAT__, __CENTER_LNG__),
                    level: 8
                };

                map = new kakao.maps.Map(mapContainer, mapOption);

                drawStoreMarkers();
                drawBaseRoutes();
                prepareScenarioRoutes();

                for (var i = 0; i < Math.min(defaultSelectedCount, scenarios.length); i++) {
                    selectedIndexes[i] = true;
                }

                document.getElementById('route-count').innerHTML = String(scenarios.length);
                updateRouteStyles();
                updateSelectedList();
                renderCandidateSelector();

                if (scenarios.length > 0) {
                    lastClickedIndex = 0;
                    renderRoutePanel(scenarios[0], false);
                } else {
                    document.getElementById('route-panel').innerHTML =
                        '<div class="panel-title">선택 가능한 이동수단 경로가 없습니다.</div>';
                }

                restart이동수단s();
            }

            function drawStoreMarkers() {
                var bounds = new kakao.maps.LatLngBounds();

                stores.forEach(function(store) {
                    if (store.latitude == null || store.longitude == null) return;

                    var position = new kakao.maps.LatLng(store.latitude, store.longitude);

                    storeById[String(store.store_id)] = store;
                    storeByName[String(store.store_name)] = store;
                    bounds.extend(position);

                    var marker = new kakao.maps.Marker({ map: map, position: position });

                    var storeName = store.store_name || "점포";
                    var storeType = store.type || "unknown";

                    var info = new kakao.maps.InfoWindow({
                        content:
                            '<div style="padding:10px 14px;font-size:15px;white-space:nowrap;">' +
                            '<b>' + storeName + '</b><br>' +
                            '유형: <b>' + storeType + '</b>' +
                            '</div>'
                    });

                    kakao.maps.event.addListener(marker, 'mouseover', function() { info.open(map, marker); });
                    kakao.maps.event.addListener(marker, 'mouseout', function() { info.close(); });
                });

                if (stores.length > 0) map.setBounds(bounds);
            }

            function drawBaseRoutes() {
                routes.forEach(function(route) {
                    var fromStore = storeById[String(route.from_id)];
                    var toStore = storeById[String(route.to_id)];

                    if (!fromStore || !toStore) return;

                    var path = [
                        new kakao.maps.LatLng(fromStore.latitude, fromStore.longitude),
                        new kakao.maps.LatLng(toStore.latitude, toStore.longitude)
                    ];

                    var polyline = new kakao.maps.Polyline({
                        path: path,
                        strokeWeight: 1,
                        strokeColor: '#C9CDD2',
                        strokeOpacity: 0.08,
                        strokeStyle: 'solid'
                    });

                    polyline.setMap(map);
                });
            }

            function prepareScenarioRoutes() {
                var bounds = new kakao.maps.LatLngBounds();

                scenarios.forEach(function(scenario, idx) {
                    var rawPath = scenario.path || [];
                    var linePath = rawPath.map(function(p) {
                        return new kakao.maps.LatLng(p.lat, p.lng);
                    });

                    if (linePath.length < 2) return;

                    linePath.forEach(function(pos) { bounds.extend(pos); });

                    var color = colors[idx % colors.length];

                    var polyline = new kakao.maps.Polyline({
                        path: linePath,
                        strokeWeight: 2,
                        strokeColor: color,
                        strokeOpacity: 0.38,
                        strokeStyle: 'solid'
                    });

                    polyline.setMap(map);

                    kakao.maps.event.addListener(polyline, 'click', function(mouseEvent) {
                        toggleRouteSelection(idx);
                        lastClickedIndex = idx;
                        renderRoutePanel(scenario, routeStates[idx] ? routeStates[idx].arrived : false);
                    });

                    kakao.maps.event.addListener(polyline, 'mouseover', function(mouseEvent) {
                        polyline.setOptions({ strokeWeight: 4, strokeOpacity: 0.85 });
                    });

                    kakao.maps.event.addListener(polyline, 'mouseout', function() {
                        updateRouteStyles();
                    });

                    var transportIcon = scenario.transport_icon || '🚚';

                    var truckOverlay = new kakao.maps.CustomOverlay({
                        position: linePath[0],
                        content: '<div class="truck-marker">' + transportIcon + ' ' + (idx + 1) + '</div>',
                        yAnchor: 0.5,
                        xAnchor: 0.5,
                        zIndex: 20 + idx
                    });

                    truckOverlay.setMap(null);

                    routeStates.push({
                        scenario: scenario,
                        polyline: polyline,
                        overlay: truckOverlay,
                        linePath: linePath,
                        segmentIndex: 0,
                        progress: 0,
                        arrived: false,
                        color: color,
                        idx: idx
                    });
                });

                if (routeStates.length > 0) map.setBounds(bounds);
            }

            function toggleRouteSelection(idx) {
                if (selectedIndexes[idx]) {
                    delete selectedIndexes[idx];
                } else {
                    selectedIndexes[idx] = true;
                }

                updateRouteStyles();
                updateSelectedList();
                restart이동수단s();
                renderCandidateSelector();
            }

            function selectAllRoutes() {
                selectedIndexes = {};
                routeStates.forEach(function(state) {
                    selectedIndexes[state.idx] = true;
                });

                updateRouteStyles();
                updateSelectedList();
                restart이동수단s();

                if (scenarios.length > 0) {
                    lastClickedIndex = 0;
                    renderRoutePanel(scenarios[0], false);
                }
            }

            function clearSelectedRoutes() {
                selectedIndexes = {};
                stop이동수단s();

                routeStates.forEach(function(state) {
                    state.overlay.setMap(null);
                    state.arrived = false;
                });

                updateRouteStyles();
                updateSelectedList();
                document.getElementById('truck-status').innerHTML = '선택된 경로 없음';
            }

            function updateRouteStyles() {
                routeStates.forEach(function(state) {
                    var selected = !!selectedIndexes[state.idx];

                    state.polyline.setOptions({
                        strokeWeight: selected ? 4 : 2,
                        strokeOpacity: selected ? 0.85 : 0.22,
                        strokeColor: selected ? state.color : '#ADB5BD'
                    });
                });
            }

            function routeLabel(idx) {
                var scenario = scenarios[idx] || {};
                var rawLabel = scenario.label || '-';
                rawLabel = String(rawLabel).replace(/^\s*\d+\.\s*/, '');
                return rawLabel;
            }

            function routeCandidateLabel(idx) {
                var scenario = scenarios[idx] || {};
                var rawLabel = routeLabel(idx);
                var score = scenario.heuristic_score;
                var scoreText = '';

                if (score !== undefined && score !== null && score !== '-') {
                    var scoreNum = Number(score);
                    if (!isNaN(scoreNum)) scoreText = ' · ' + Math.round(scoreNum) + '점';
                }

                var grade = scenario.heuristic_grade || scenario.recommendation_grade || scenario.grade || '';
                var gradeText = grade ? ' · ' + grade : '';

                var transportText = scenario.transport_type ? ' · ' + (scenario.transport_icon || '') + ' ' + scenario.transport_type : '';
                return '<span class="candidate-rank">AI ' + (idx + 1) + '위</span> | ' + rawLabel + scoreText + gradeText + transportText;
            }

            var candidateSelectorOpen = false;

            function toggleCandidateSelector() {
                candidateSelectorOpen = !candidateSelectorOpen;

                var list = document.getElementById('candidate-list');
                var icon = document.getElementById('candidate-toggle-icon');

                if (list) {
                    if (candidateSelectorOpen) {
                        list.classList.add('open');
                    } else {
                        list.classList.remove('open');
                    }
                }

                if (icon) {
                    icon.innerText = candidateSelectorOpen ? '▲' : '▼';
                }
            }

            function renderCandidateSelector() {
                var box = document.getElementById('candidate-selector');
                if (!box) return;

                if (!scenarios || scenarios.length === 0) {
                    box.innerHTML = '<div class="candidate-title" onclick="toggleCandidateSelector()"><span class="candidate-title-left">🚚 지도에 표시할 AI 추천 후보 선택</span><span id="candidate-toggle-icon" class="candidate-toggle-icon">▼</span></div><div id="candidate-list" class="candidate-list">표시할 후보가 없습니다.</div>';
                    return;
                }

                var selectedCount = Object.keys(selectedIndexes).length;
                var html = '';
                html += '<div class="candidate-title" onclick="toggleCandidateSelector()">';
                html += '<span class="candidate-title-left">🚚 지도에 표시할 AI 추천 후보 선택 <span style="font-size:12px; color:#666;">(' + selectedCount + '/' + scenarios.length + ')</span></span>';
                html += '<span id="candidate-toggle-icon" class="candidate-toggle-icon">' + (candidateSelectorOpen ? '▲' : '▼') + '</span>';
                html += '</div>';

                html += '<div id="candidate-list" class="candidate-list' + (candidateSelectorOpen ? ' open' : '') + '">';

                scenarios.forEach(function(scenario, idx) {
                    var checked = selectedIndexes[idx] ? 'checked' : '';
                    html += '<label class="candidate-item">';
                    html += '<input type="checkbox" ' + checked + ' onchange="setRouteSelectionFromCheckbox(' + idx + ', this.checked)">';
                    html += '<span>' + routeCandidateLabel(idx) + '</span>';
                    html += '</label>';
                });

                html += '</div>';
                box.innerHTML = html;
            }

            function setRouteSelectionFromCheckbox(idx, checked) {
                if (checked) {
                    selectedIndexes[idx] = true;
                    lastClickedIndex = idx;
                    if (scenarios[idx]) renderRoutePanel(scenarios[idx], routeStates[idx] ? routeStates[idx].arrived : false);
                } else {
                    delete selectedIndexes[idx];
                }

                updateRouteStyles();
                updateSelectedList();
                restart이동수단s();
            }

            function updateSelectedList() {
                var selectedNames = [];

                Object.keys(selectedIndexes).forEach(function(key) {
                    var idx = Number(key);
                    if (scenarios[idx]) {
                        selectedNames.push((idx + 1) + '. ' + routeLabel(idx));
                    }
                });

                document.getElementById('selected-count').innerHTML = String(selectedNames.length);

                if (selectedNames.length === 0) {
                    document.getElementById('selected-list').innerHTML = '선택된 경로가 없습니다.';
                } else {
                    document.getElementById('selected-list').innerHTML =
                        '<b>선택된 경로</b><br>' + selectedNames.join('<br>');
                }

                renderCandidateSelector();
            }

            function get이동수단Offset(idx) {
                var step = ((idx % 7) - 3) * 0.00008;
                return { lat: step, lng: step };
            }

            function offsetLatLng(position, idx) {
                var offset = get이동수단Offset(idx);
                return new kakao.maps.LatLng(position.getLat() + offset.lat, position.getLng() + offset.lng);
            }

            function interpolate(start, end, ratio) {
                var lat = start.getLat() + (end.getLat() - start.getLat()) * ratio;
                var lng = start.getLng() + (end.getLng() - start.getLng()) * ratio;
                return new kakao.maps.LatLng(lat, lng);
            }

            function restart이동수단s() {
                stop이동수단s();

                truckStates = [];

                routeStates.forEach(function(state) {
                    state.segmentIndex = 0;
                    state.progress = 0;
                    state.arrived = false;

                    if (selectedIndexes[state.idx]) {
                        if (state.linePath.length > 0) {
                            state.overlay.setPosition(offsetLatLng(state.linePath[0], state.idx));
                            state.overlay.setMap(map);
                            truckStates.push(state);
                        }
                    } else {
                        state.overlay.setMap(null);
                    }
                });

                if (truckStates.length === 0) {
                    document.getElementById('truck-status').innerHTML = '선택된 경로 없음';
                    return;
                }

                isPaused = false;
                document.getElementById('truck-status').innerHTML = '선택한 여러 경로에서 이동수단 동시 이동 중';

                animationTimer = setInterval(function() {
                    if (isPaused) return;

                    var allArrived = true;

                    truckStates.forEach(function(state) {
                        if (state.arrived) return;

                        allArrived = false;

                        if (state.segmentIndex >= state.linePath.length - 1) {
                            state.arrived = true;
                            state.overlay.setPosition(offsetLatLng(state.linePath[state.linePath.length - 1], state.idx));
                            return;
                        }

                        state.progress += 0.005 * speedMultiplier * Number(state.scenario.transport_speed_factor || 1);

                        if (state.progress >= 1) {
                            state.progress = 0;
                            state.segmentIndex += 1;

                            if (state.segmentIndex >= state.linePath.length - 1) {
                                state.arrived = true;
                                state.overlay.setPosition(offsetLatLng(state.linePath[state.linePath.length - 1], state.idx));
                                return;
                            }
                        }

                        var nextPosition = interpolate(
                            state.linePath[state.segmentIndex],
                            state.linePath[state.segmentIndex + 1],
                            state.progress
                        );

                        state.overlay.setPosition(offsetLatLng(nextPosition, state.idx));
                    });

                    if (allArrived) {
                        stop이동수단s();
                        document.getElementById('truck-status').innerHTML = '선택한 모든 이동수단 도착 완료';

                        if (lastClickedIndex !== null && scenarios[lastClickedIndex]) {
                            renderRoutePanel(scenarios[lastClickedIndex], true);
                        }
                    }
                }, 20);
            }

            function stop이동수단s() {
                if (animationTimer !== null) {
                    clearInterval(animationTimer);
                    animationTimer = null;
                }
            }

            function pause이동수단s() {
                isPaused = true;
                document.getElementById('truck-status').innerHTML = '일시정지';
            }

            function resume이동수단s() {
                isPaused = false;
                document.getElementById('truck-status').innerHTML = '선택한 여러 경로에서 이동수단 동시 이동 중';
            }

            function getMaxQty(items) {
                var maxQty = 1;

                Object.keys(items || {}).forEach(function(storeName) {
                    var item = items[storeName];
                    maxQty = Math.max(maxQty, Number(item.before || 0));
                    maxQty = Math.max(maxQty, Number(item.after || 0));
                });

                return maxQty;
            }

            function pct(value, maxQty) {
                if (!maxQty || maxQty <= 0) return 0;
                return Math.max(4, Math.min(100, (Number(value || 0) / maxQty) * 100));
            }

            function renderRoutePanel(scenario, arrived) {
                var panel = document.getElementById('route-panel');
                var inv = scenario.store_inventory || {};
                var maxQty = getMaxQty(inv);

                var html = '';
                html += '<div class="panel-title">🛣 클릭한 경로 결과: ' + (scenario.label || '-') + '</div>';

                html += '<div class="route-grid">';
                html += '<div class="route-mini"><div class="route-label">상품명</div><div class="route-value">' + (scenario.product_name || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">경로</div><div class="route-value">' + (scenario.source_store || '-') + ' → ' + (scenario.target_store || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">추천 수량</div><div class="route-value">' + (scenario.move_qty || 0) + '개</div></div>';
                html += '<div class="route-mini"><div class="route-label">예상 비용</div><div class="route-value">' + (scenario.estimated_cost || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">추천 전략</div><div class="route-value">' + (scenario.recommended_path || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">추천 등급</div><div class="route-value">' + (scenario.heuristic_grade || '-') + '</div></div>';
                if (scenario.route_path_type) {
                    html += '<div class="route-mini"><div class="route-label">이동 방식</div><div class="route-value">' + scenario.route_path_type + '</div></div>';
                }
                html += '<div class="route-mini"><div class="route-label">이동수단</div><div class="route-value">' + (scenario.transport_icon || '🚚') + ' ' + (scenario.transport_type || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">이동수단 비용</div><div class="route-value">' + (scenario.transport_cost || '-') + '원</div></div>';
                html += '<div class="route-mini"><div class="route-label">이동거리</div><div class="route-value">' + (scenario.distance_km || '-') + 'km</div></div>';
                html += '<div class="route-mini"><div class="route-label">총점</div><div class="route-value">' + (scenario.heuristic_score || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">이동 상태</div><div class="route-value">' + (arrived ? '도착 완료' : '이동 전/이동 중') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">경로 노드</div><div class="route-value">' + (scenario.path_names || []).join(' → ') + '</div></div>';
                html += '</div>';

                html += '<div class="reason-box">';
                html += '<b>추천 이유:</b> ' + (scenario.reason || '-') + '<br>';
                html += '<b>이동수단 안내:</b> 현재 시뮬레이션은 ' + (scenario.transport_type || '-') + ' 기준이며, 이동수단별 비용은 앱의 표에서 비교할 수 있습니다.<br>';
                html += '<b>안내:</b> 지도 위 경로선을 클릭하면 선택/해제되고, 해당 경로의 결과가 이 패널에 표시됩니다.';
                html += '</div>';

                html += '<div class="panel-title" style="font-size:18px;">📦 클릭 경로 재고 변화</div>';
                html += '<div class="inventory-grid">';

                Object.keys(inv).forEach(function(storeName) {
                    var item = inv[storeName];
                    var beforeQty = Number(item.before || 0);
                    var afterQty = Number(item.after || 0);
                    var changeQty = Number(item.change || 0);
                    var changeClass = changeQty >= 0 ? 'change-plus' : 'change-minus';
                    var changeText = changeQty >= 0 ? '+' + changeQty : String(changeQty);

                    html += '<div class="inventory-card">';
                    html += '<div class="store-name">' + storeName + '</div>';
                    html += '<div class="store-role">' + (item.role || '-') + ' / ' + (item.product_name || '-') + '</div>';
                    html += '<div class="bar-label"><span>이동 전 재고</span><b>' + beforeQty + '개</b></div>';
                    html += '<div class="bar-track"><div class="bar-before" style="width:' + pct(beforeQty, maxQty) + '%;"></div></div>';
                    html += '<div class="bar-label"><span>이동 후 재고</span><b>' + afterQty + '개</b></div>';
                    html += '<div class="bar-track"><div class="bar-after" style="width:' + pct(afterQty, maxQty) + '%;"></div></div>';
                    html += '<div>변화량: <span class="' + changeClass + '">' + changeText + '개</span></div>';
                    html += '</div>';
                });

                html += '</div>';
                panel.innerHTML = html;
            }
        </script>
    </body>
    </html>
    """

    html = html.replace("__KAKAO_KEY__", kakao_js_key)
    html = html.replace("__CENTER_LAT__", str(center_lat))
    html = html.replace("__CENTER_LNG__", str(center_lng))
    html = html.replace("__STORES_JSON__", stores_json)
    html = html.replace("__ROUTES_JSON__", routes_json)
    html = html.replace("__SCENARIOS_JSON__", scenarios_json)
    html = html.replace("__SPEED__", str(speed_multiplier))
    html = html.replace("__DEFAULT_SELECTED_COUNT__", str(default_selected_count))

    st.iframe(html, height=1060, width="stretch")


def show_kakao_map_with_truck(
    stores,
    routes,
    kakao_js_key,
    truck_path,
    speed_multiplier=1.0,
    inventory_changes=None,
):
    inventory_changes = inventory_changes or {}

    scenario = {
        "label": inventory_changes.get("product_name", "이동수단 이동 경로"),
        "product_name": inventory_changes.get("product_name", "-"),
        "source_store": inventory_changes.get("source_store", "-"),
        "target_store": inventory_changes.get("target_store", "-"),
        "move_qty": inventory_changes.get("move_qty", 0),
        "recommended_path": inventory_changes.get("recommended_path", "-"),
        "estimated_cost": inventory_changes.get("estimated_cost", "-"),
        "heuristic_score": inventory_changes.get("heuristic_score", "-"),
        "reason": inventory_changes.get("reason", "-"),
        "path_names": [p.get("name", "") for p in truck_path],
        "path": truck_path,
        "store_inventory": inventory_changes.get("store_inventory", {}),
    }

    show_kakao_map_with_multi_trucks(
        stores=stores,
        routes=routes,
        kakao_js_key=kakao_js_key,
        truck_scenarios=[scenario],
        speed_multiplier=speed_multiplier,
        default_selected_count=1,
    )


def show_store_matching_map(
    stores,
    routes,
    final_recommendations,
    kakao_js_key,
    selected_store_name=None,
):
    """
    브라우저/휴대폰 GPS 기준으로 주변 점포를 표시하는 재고 매칭 지도.

    색상 기준:
    - 초록색: 내 위치
    - 빨간색: 긴급 수요
    - 노란색: 추천 가능
    - 파란색: 일반 점포
    """
    stores_data = stores.copy().dropna(subset=["latitude", "longitude"])
    routes_data = routes.copy() if routes is not None else None
    rec_data = final_recommendations.copy() if final_recommendations is not None else None

    if stores_data.empty:
        components.html("<p>지도에 표시할 위치 데이터가 없습니다.</p>", height=200)
        return

    kakao_js_key = str(kakao_js_key).strip()

    # GPS가 실패했을 때 사용할 fallback 중심점
    if selected_store_name and selected_store_name in stores_data["store_name"].astype(str).values:
        center_row = stores_data[stores_data["store_name"].astype(str) == str(selected_store_name)].iloc[0]
    else:
        center_row = stores_data.iloc[0]
        selected_store_name = str(center_row["store_name"])

    center_lat = float(center_row["latitude"])
    center_lng = float(center_row["longitude"])

    store_status = {}

    for _, store in stores_data.iterrows():
        store_name = str(store["store_name"])

        store_status[store_name] = {
            "store_name": store_name,
            "status": "일반",
            "color": "#228BE6",
            "items": [],
        }

    def _to_number(value, default=0):
        try:
            if value is None:
                return default

            text = str(value).replace(",", "").replace("원", "").strip()

            if text in ["", "-", "None", "nan", "NaN"]:
                return default

            return float(text)
        except Exception:
            return default

    def _get_qty(row):
        qty_columns = [
            "suggested_qty",
            "suggested_transfer_qty",
            "move_qty",
            "recommended_qty",
            "transfer_qty",
            "추천 수량",
        ]

        for col in qty_columns:
            try:
                if col in row.index:
                    value = _to_number(row.get(col), None)

                    if value is not None and value > 0:
                        return int(round(value))
            except Exception:
                continue

        return 0

    def _format_cost(value):
        try:
            text = str(value).replace(",", "").replace("원", "").strip()

            if text in ["", "-", "None", "nan", "NaN"]:
                return "-"

            numeric_value = float(text)
            return f"{numeric_value:,.0f}원"
        except Exception:
            text = str(value)
            return text if text not in ["None", "nan", "NaN"] else "-"

    if rec_data is not None and not rec_data.empty:
        for _, row in rec_data.iterrows():
            target_store = str(row.get("target_store", "-"))
            source_store = str(row.get("source_store", "-"))

            if target_store not in store_status:
                continue

            qty = _get_qty(row)

            if qty <= 0:
                continue

            score = _to_number(row.get("heuristic_score", 0), 0)
            grade_text = str(row.get("heuristic_grade", ""))
            strategy_text = str(row.get("final_recommendation", "-"))

            item = {
                "product_name": str(row.get("product_name", "-")),
                "source_store": source_store,
                "target_store": target_store,
                "suggested_qty": str(qty),
                "estimated_cost": _format_cost(row.get("estimated_cost", "-")),
                "final_recommendation": strategy_text,
                "reason": str(row.get("reason", "-")),
                "heuristic_score": str(row.get("heuristic_score", "-")),
                "heuristic_grade": str(row.get("heuristic_grade", "-")),
            }

            store_status[target_store]["items"].append(item)

            # 긴급/추천/일반 색상 분류
            if qty >= 100 or score >= 80 or "최적" in grade_text or "긴급" in grade_text or "최우선" in grade_text:
                store_status[target_store]["status"] = "긴급"
                store_status[target_store]["color"] = "#E03131"
            elif store_status[target_store]["status"] != "긴급":
                store_status[target_store]["status"] = "추천"
                store_status[target_store]["color"] = "#FAB005"

    stores_json = _records_json(stores_data)
    routes_json = _records_json(routes_data) if routes_data is not None else "[]"
    status_json = json.dumps(store_status, ensure_ascii=False)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
        <style>
            html, body {
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                font-family: Arial, sans-serif;
                color: #222;
                background: #ffffff;
            }

            .wrap {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 14px;
                width: 100%;
            }

            #map {
                width: 100%;
                height: 620px;
                border-radius: 16px;
                border: 1px solid #dddddd;
                overflow: hidden;
            }

            #detail-panel {
                height: 620px;
                overflow-y: auto;
                border-radius: 16px;
                border: 1px solid #e5e5e5;
                background: #ffffff;
                box-shadow: 0 4px 16px rgba(0,0,0,0.06);
                padding: 18px;
                box-sizing: border-box;
            }

            .panel-title {
                font-size: 22px;
                font-weight: 900;
                margin-bottom: 8px;
                color: #222;
            }

            .panel-sub {
                font-size: 14px;
                color: #555;
                margin-bottom: 14px;
                line-height: 1.5;
            }

            .gps-box {
                padding: 12px 14px;
                border-radius: 14px;
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                margin-bottom: 12px;
                font-size: 13.5px;
                color: #444;
                line-height: 1.45;
            }

            .legend {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                margin-bottom: 14px;
            }

            .legend-item {
                font-size: 13px;
                padding: 6px 9px;
                border-radius: 999px;
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                color: #222;
            }

            .dot {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 5px;
            }

            .store-marker {
                width: 18px;
                height: 18px;
                border-radius: 50%;
                border: 3px solid white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.28);
                transform: translate(-9px, -9px);
                cursor: pointer;
            }

            .my-location-marker {
                width: 28px;
                height: 28px;
                border-radius: 50%;
                background:#2F9E44;
                border: 4px solid white;
                box-shadow: 0 3px 12px rgba(47,158,68,0.55);
                transform: translate(-14px, -14px);
                position: relative;
            }

            .my-location-marker:after {
                content: '';
                position: absolute;
                left: -8px;
                top: -8px;
                width: 36px;
                height: 36px;
                border-radius: 50%;
                border: 2px solid rgba(47,158,68,0.32);
            }

            .near-store-row {
                border: 1px solid #e9ecef;
                border-radius: 13px;
                padding: 10px 11px;
                margin-bottom: 8px;
                background: #ffffff;
                cursor: pointer;
            }

            .near-store-row:hover {
                background: #fff9db;
            }

            .near-store-title {
                font-size: 14px;
                font-weight: 900;
                color: #222;
                margin-bottom: 4px;
            }

            .near-store-meta {
                font-size: 12.5px;
                color: #555;
                line-height: 1.45;
            }

            .item-card {
                border: 1px solid #e9ecef;
                border-radius: 14px;
                padding: 12px 14px;
                margin-bottom: 10px;
                background: #f8f9fa;
            }

            .compact-item-card {
                padding: 11px 14px;
            }

            .item-title {
                font-size: 16px;
                font-weight: 900;
                margin-bottom: 5px;
                color: #222;
            }

            .item-row {
                font-size: 13.5px;
                color: #444;
                line-height: 1.45;
            }

            .empty-box {
                padding: 16px;
                border-radius: 14px;
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                color: #666;
                line-height: 1.5;
            }

            @media (max-width: 900px) {
                .wrap {
                    grid-template-columns: 1fr;
                }

                #map {
                    height: 500px;
                }

                #detail-panel {
                    height: auto;
                    max-height: none;
                }
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div id="map"></div>

            <div id="detail-panel">
                <div class="panel-title">내 주변 재고 매칭 지도</div>
                <div id="gps-status" class="gps-box">현재 위치를 확인하는 중...</div>

                <div class="legend">
                    <span class="legend-item"><span class="dot" style="background:#2F9E44;"></span>내 위치</span>
                    <span class="legend-item"><span class="dot" style="background:#E03131;"></span>긴급</span>
                    <span class="legend-item"><span class="dot" style="background:#FAB005;"></span>추천</span>
                    <span class="legend-item"><span class="dot" style="background:#228BE6;"></span>일반</span>
                </div>

                <div id="store-detail" class="empty-box">
                    주변 점포를 불러오는 중...
                </div>
            </div>
        </div>

        <script>
            var stores = __STORES_JSON__;
            var routes = __ROUTES_JSON__;
            var storeStatus = __STATUS_JSON__;
            var fallbackCenter = { lat: __CENTER_LAT__, lng: __CENTER_LNG__ };

            var map = null;
            var storeById = {};
            var storeByName = {};
            var storeMarkers = [];
            var routeLines = [];
            var myLocationOverlay = null;
            var currentLat = fallbackCenter.lat;
            var currentLng = fallbackCenter.lng;
            var nearbyStores = [];

            var script = document.createElement('script');
            script.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=__KAKAO_KEY__&autoload=false';

            script.onload = function() {
                kakao.maps.load(function() {
                    initMap();
                });
            };

            script.onerror = function() {
                document.getElementById('map').innerHTML =
                    '<div style="padding:20px;color:#d9480f;font-weight:bold;">카카오맵 SDK를 불러오지 못했습니다. JavaScript 키와 도메인 등록을 확인하세요.</div>';
            };

            document.head.appendChild(script);

            function escapeHtml(value) {
                if (value === null || value === undefined) return '-';
                return String(value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#039;');
            }

            function distanceKm(lat1, lng1, lat2, lng2) {
                var R = 6371;
                var dLat = (lat2 - lat1) * Math.PI / 180;
                var dLng = (lng2 - lng1) * Math.PI / 180;
                var a =
                    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                    Math.sin(dLng / 2) * Math.sin(dLng / 2);
                var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                return R * c;
            }

            function initMap() {
                var mapContainer = document.getElementById('map');
                var mapOption = {
                    center: new kakao.maps.LatLng(fallbackCenter.lat, fallbackCenter.lng),
                    level: 5
                };

                map = new kakao.maps.Map(mapContainer, mapOption);

                stores.forEach(function(store) {
                    storeById[String(store.store_id)] = store;
                    storeByName[String(store.store_name)] = store;
                });

                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(position) {
                            currentLat = position.coords.latitude;
                            currentLng = position.coords.longitude;

                            document.getElementById('gps-status').innerHTML =
                                '<b>내 위치 기준</b>으로 가까운 점포를 표시 중';

                            drawNearbyMap(true);
                        },
                        function(error) {
                            document.getElementById('gps-status').innerHTML =
                                '<b>위치 권한을 허용하지 않아</b> 기본 위치 기준으로 표시 중';

                            drawNearbyMap(false);
                        },
                        {
                            enableHighAccuracy: true,
                            timeout: 8000,
                            maximumAge: 60000
                        }
                    );
                } else {
                    document.getElementById('gps-status').innerHTML =
                        '<b>브라우저 위치 기능을 지원하지 않아</b> 기본 위치 기준으로 표시 중';

                    drawNearbyMap(false);
                }
            }

            function clearMapObjects() {
                storeMarkers.forEach(function(obj) {
                    if (obj.overlay) obj.overlay.setMap(null);
                    if (obj.clickMarker) obj.clickMarker.setMap(null);
                });
                storeMarkers = [];

                routeLines.forEach(function(line) {
                    line.setMap(null);
                });
                routeLines = [];

                if (myLocationOverlay) {
                    myLocationOverlay.setMap(null);
                    myLocationOverlay = null;
                }
            }

            function drawNearbyMap(hasGps) {
                clearMapObjects();

                var centerPosition = new kakao.maps.LatLng(currentLat, currentLng);
                map.setCenter(centerPosition);
                map.setLevel(5);

                if (hasGps) {
                    myLocationOverlay = new kakao.maps.CustomOverlay({
                        position: centerPosition,
                        content: '<div class="my-location-marker"></div>',
                        yAnchor: 0.5,
                        xAnchor: 0.5,
                        zIndex: 100
                    });
                    myLocationOverlay.setMap(map);
                }

                nearbyStores = stores
                    .filter(function(store) {
                        return store.latitude !== null && store.longitude !== null &&
                               store.latitude !== undefined && store.longitude !== undefined;
                    })
                    .map(function(store) {
                        var dist = distanceKm(
                            currentLat,
                            currentLng,
                            Number(store.latitude),
                            Number(store.longitude)
                        );
                        var storeName = String(store.store_name);
                        var statusInfo = storeStatus[storeName] || {};
                        return {
                            store: store,
                            distance_km: dist,
                            status: statusInfo.status || '일반',
                            color: statusInfo.color || '#228BE6',
                            items: statusInfo.items || []
                        };
                    })
                    .sort(function(a, b) {
                        return a.distance_km - b.distance_km;
                    })
                    .slice(0, 20);

                drawStoreMarkers();
                drawNearbyRoutes();
                renderNearbyList();
            }

            function drawNearbyRoutes() {
                var nearbyNameSet = {};
                nearbyStores.forEach(function(item) {
                    nearbyNameSet[String(item.store.store_name)] = true;
                });

                routes.forEach(function(route) {
                    var fromStore = storeById[String(route.from_id)];
                    var toStore = storeById[String(route.to_id)];

                    if (!fromStore || !toStore) return;

                    if (!nearbyNameSet[String(fromStore.store_name)] && !nearbyNameSet[String(toStore.store_name)]) {
                        return;
                    }

                    var path = [
                        new kakao.maps.LatLng(fromStore.latitude, fromStore.longitude),
                        new kakao.maps.LatLng(toStore.latitude, toStore.longitude)
                    ];

                    var polyline = new kakao.maps.Polyline({
                        path: path,
                        strokeWeight: 2,
                        strokeColor: '#CED4DA',
                        strokeOpacity: 0.25,
                        strokeStyle: 'solid'
                    });

                    polyline.setMap(map);
                    routeLines.push(polyline);
                });
            }

            function drawStoreMarkers() {
                nearbyStores.forEach(function(item) {
                    var store = item.store;
                    var storeName = String(store.store_name);
                    var color = item.color;
                    var status = item.status;

                    var position = new kakao.maps.LatLng(store.latitude, store.longitude);

                    var overlay = new kakao.maps.CustomOverlay({
                        position: position,
                        content: '<div class="store-marker" style="background:' + color + ';"></div>',
                        yAnchor: 0.5,
                        xAnchor: 0.5,
                        zIndex: status === '긴급' ? 50 : 30
                    });

                    overlay.setMap(map);

                    var clickArea = new kakao.maps.Marker({
                        map: map,
                        position: position,
                        opacity: 0
                    });

                    kakao.maps.event.addListener(clickArea, 'click', function() {
                        renderStoreDetail(storeName);
                        map.panTo(position);
                    });

                    var info = new kakao.maps.InfoWindow({
                        content:
                            '<div style="padding:9px 12px;font-size:14px;white-space:nowrap;">' +
                            '<b>' + escapeHtml(storeName) + '</b><br>' +
                            '상태: <b>' + escapeHtml(status) + '</b><br>' +
                            '거리: <b>' + item.distance_km.toFixed(2) + 'km</b>' +
                            '</div>'
                    });

                    kakao.maps.event.addListener(clickArea, 'mouseover', function() {
                        info.open(map, clickArea);
                    });

                    kakao.maps.event.addListener(clickArea, 'mouseout', function() {
                        info.close();
                    });

                    storeMarkers.push({ overlay: overlay, clickMarker: clickArea });
                });
            }

            function renderNearbyList() {
                var detail = document.getElementById('store-detail');

                var html = '';
                html += '<div class="panel-title">근처 점포 TOP 5</div>';
                html += '<div class="panel-sub">점포를 누르면 추천 상품과 이동 정보를 확인할 수 있습니다.</div>';

                nearbyStores.slice(0, 5).forEach(function(item, idx) {
                    var storeName = String(item.store.store_name);
                    var itemsCount = item.items ? item.items.length : 0;

                    html += '<div class="near-store-row" onclick="renderStoreDetail(\\'' + escapeHtml(storeName).replace(/'/g, "\\\\'") + '\\')">';
                    html += '<div class="near-store-title">' + (idx + 1) + '. ' + escapeHtml(storeName) + '</div>';
                    html += '<div class="near-store-meta">거리 ' + item.distance_km.toFixed(2) + 'km · 상태 ' + escapeHtml(item.status) + ' · 추천 ' + itemsCount + '건</div>';
                    html += '</div>';
                });

                detail.innerHTML = html;
            }

            function renderStoreDetail(storeName) {
                var detail = document.getElementById('store-detail');
                var info = storeStatus[storeName] || {};
                var items = info.items || [];

                var nearInfo = null;
                nearbyStores.forEach(function(item) {
                    if (String(item.store.store_name) === String(storeName)) {
                        nearInfo = item;
                    }
                });

                var distanceText = nearInfo ? nearInfo.distance_km.toFixed(2) + 'km' : '-';

                var html = '';
                html += '<div class="panel-title">' + escapeHtml(storeName) + '</div>';
                html += '<div class="panel-sub">상태: <b>' + escapeHtml(info.status || '-') + '</b> · 거리: <b>' + escapeHtml(distanceText) + '</b></div>';

                if (items.length === 0) {
                    html += '<div class="empty-box">현재 표시할 필요 상품 또는 추천 후보가 없습니다.</div>';
                    html += '<div style="margin-top:12px;"><button onclick="renderNearbyList()" style="padding:10px 14px;border-radius:12px;border:1px solid #ddd;background:#fff;cursor:pointer;">근처 점포 목록으로 돌아가기</button></div>';
                    detail.innerHTML = html;
                    return;
                }

                html += '<div class="panel-sub">필요 상품 ' + items.length + '건</div>';

                items.slice(0, 20).forEach(function(item, idx) {
                    html += '<div class="item-card compact-item-card">';
                    html += '<div class="item-title">' + (idx + 1) + '. ' + escapeHtml(item.product_name || '-') + ': ' + escapeHtml(item.suggested_qty || '-') + '개</div>';
                    html += '<div class="item-row"><b>보낼 점포:</b> ' + escapeHtml(item.source_store || '-') + '</div>';
                    html += '</div>';
                });

                html += '<div style="margin-top:12px;"><button onclick="renderNearbyList()" style="padding:10px 14px;border-radius:12px;border:1px solid #ddd;background:#fff;cursor:pointer;">근처 점포 목록으로 돌아가기</button></div>';
                detail.innerHTML = html;
            }
        </script>
    </body>
    </html>
    """

    html = html.replace("__KAKAO_KEY__", kakao_js_key)
    html = html.replace("__CENTER_LAT__", str(center_lat))
    html = html.replace("__CENTER_LNG__", str(center_lng))
    html = html.replace("__STORES_JSON__", stores_json)
    html = html.replace("__ROUTES_JSON__", routes_json)
    html = html.replace("__STATUS_JSON__", status_json)

    components.html(html, height=1180, scrolling=True)


import json
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
                        strokeWeight: 2,
                        strokeColor: '#C9CDD2',
                        strokeOpacity: 0.55,
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
                        strokeWeight: 7,
                        strokeColor: '#FFD43B',
                        strokeOpacity: 0.95,
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
    components.html(html, height=720, scrolling=False)


def show_kakao_map_with_highlights(stores, routes, kakao_js_key, highlight_paths):
    html = create_kakao_map_html(stores, routes, kakao_js_key, highlight_paths)
    components.html(html, height=720, scrolling=False)


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
        components.html("<p>지도에 표시할 위치 데이터가 없습니다.</p>", height=200)
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
            <b>🚚 지도 클릭 기반 Multi-Truck 이동 시뮬레이션</b><br>
            상태: <span id="truck-status">준비 중</span><br>
            현재 배속: <b><span id="speed-text">__SPEED__</span>x</b> /
            전체 후보 경로 수: <b><span id="route-count">0</span>개</b> /
            선택 경로 수: <b><span id="selected-count">0</span>개</b>
            <div style="margin-top:10px;">
                <button onclick="restartTrucks()">선택 경로 Truck 재생</button>
                <button onclick="selectAllRoutes()">전체 경로 선택</button>
                <button onclick="clearSelectedRoutes()">선택 해제</button>
                <button onclick="pauseTrucks()">일시정지</button>
                <button onclick="resumeTrucks()">다시 재생</button>
            </div>
            <div class="click-guide">
                ① 지도 위 색깔 경로선을 클릭하면 선택/해제됩니다.<br>
                ② 클릭한 경로의 추천 결과와 Inventory 변화가 아래에 표시됩니다.<br>
                ③ 여러 경로를 선택한 뒤 <b>선택 경로 Truck 재생</b>을 누르면 Truck 여러 대가 동시에 이동합니다.
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

                if (scenarios.length > 0) {
                    lastClickedIndex = 0;
                    renderRoutePanel(scenarios[0], false);
                } else {
                    document.getElementById('route-panel').innerHTML =
                        '<div class="panel-title">선택 가능한 Truck 경로가 없습니다.</div>';
                }

                restartTrucks();
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
                        strokeWeight: 2,
                        strokeColor: '#C9CDD2',
                        strokeOpacity: 0.25,
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
                        strokeWeight: 5,
                        strokeColor: color,
                        strokeOpacity: 0.5,
                        strokeStyle: 'solid'
                    });

                    polyline.setMap(map);

                    kakao.maps.event.addListener(polyline, 'click', function(mouseEvent) {
                        toggleRouteSelection(idx);
                        lastClickedIndex = idx;
                        renderRoutePanel(scenario, routeStates[idx] ? routeStates[idx].arrived : false);
                    });

                    kakao.maps.event.addListener(polyline, 'mouseover', function(mouseEvent) {
                        polyline.setOptions({ strokeWeight: 9, strokeOpacity: 1.0 });
                    });

                    kakao.maps.event.addListener(polyline, 'mouseout', function() {
                        updateRouteStyles();
                    });

                    var truckOverlay = new kakao.maps.CustomOverlay({
                        position: linePath[0],
                        content: '<div class="truck-marker">🚚 ' + (idx + 1) + '</div>',
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
                restartTrucks();
            }

            function selectAllRoutes() {
                selectedIndexes = {};
                routeStates.forEach(function(state) {
                    selectedIndexes[state.idx] = true;
                });

                updateRouteStyles();
                updateSelectedList();
                restartTrucks();

                if (scenarios.length > 0) {
                    lastClickedIndex = 0;
                    renderRoutePanel(scenarios[0], false);
                }
            }

            function clearSelectedRoutes() {
                selectedIndexes = {};
                stopTrucks();

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
                        strokeWeight: selected ? 9 : 4,
                        strokeOpacity: selected ? 1.0 : 0.35,
                        strokeColor: selected ? state.color : '#ADB5BD'
                    });
                });
            }

            function updateSelectedList() {
                var selectedNames = [];

                Object.keys(selectedIndexes).forEach(function(key) {
                    var idx = Number(key);
                    if (scenarios[idx]) {
                        selectedNames.push((idx + 1) + '. ' + (scenarios[idx].label || '-'));
                    }
                });

                document.getElementById('selected-count').innerHTML = String(selectedNames.length);

                if (selectedNames.length === 0) {
                    document.getElementById('selected-list').innerHTML = '선택된 경로가 없습니다. 지도 위 경로선을 클릭해 선택하세요.';
                } else {
                    document.getElementById('selected-list').innerHTML =
                        '<b>선택된 경로</b><br>' + selectedNames.join('<br>');
                }
            }

            function getTruckOffset(idx) {
                // 같은 경로를 여러 Truck이 지나갈 때 완전히 겹쳐 보이지 않도록 아주 작은 시각적 오프셋 적용
                var step = ((idx % 7) - 3) * 0.00008;
                return { lat: step, lng: step };
            }

            function offsetLatLng(position, idx) {
                var offset = getTruckOffset(idx);
                return new kakao.maps.LatLng(position.getLat() + offset.lat, position.getLng() + offset.lng);
            }

            function interpolate(start, end, ratio) {
                var lat = start.getLat() + (end.getLat() - start.getLat()) * ratio;
                var lng = start.getLng() + (end.getLng() - start.getLng()) * ratio;
                return new kakao.maps.LatLng(lat, lng);
            }

            function restartTrucks() {
                stopTrucks();

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
                document.getElementById('truck-status').innerHTML = '선택한 여러 경로에서 Truck 동시 이동 중';

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

                        state.progress += 0.005 * speedMultiplier;

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
                        stopTrucks();
                        document.getElementById('truck-status').innerHTML = '선택한 모든 Truck 도착 완료';

                        if (lastClickedIndex !== null && scenarios[lastClickedIndex]) {
                            renderRoutePanel(scenarios[lastClickedIndex], true);
                        }
                    }
                }, 20);
            }

            function stopTrucks() {
                if (animationTimer !== null) {
                    clearInterval(animationTimer);
                    animationTimer = null;
                }
            }

            function pauseTrucks() {
                isPaused = true;
                document.getElementById('truck-status').innerHTML = '일시정지';
            }

            function resumeTrucks() {
                isPaused = false;
                document.getElementById('truck-status').innerHTML = '선택한 여러 경로에서 Truck 동시 이동 중';
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
                html += '<div class="route-mini"><div class="route-label">추천 방식</div><div class="route-value">' + (scenario.recommended_path || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">휴리스틱 점수</div><div class="route-value">' + (scenario.heuristic_score || '-') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">Truck 상태</div><div class="route-value">' + (arrived ? '도착 완료' : '이동 전/이동 중') + '</div></div>';
                html += '<div class="route-mini"><div class="route-label">경로 노드</div><div class="route-value">' + (scenario.path_names || []).join(' → ') + '</div></div>';
                html += '</div>';

                html += '<div class="reason-box">';
                html += '<b>추천 이유:</b> ' + (scenario.reason || '-') + '<br>';
                html += '<b>선택 상태:</b> ' + (selectedIndexes[scenarios.indexOf(scenario)] ? '선택됨' : '선택 안 됨') + '<br>';
                html += '<b>안내:</b> 지도 위 경로선을 클릭하면 선택/해제되고, 해당 경로의 결과가 이 패널에 표시됩니다.';
                html += '</div>';

                html += '<div class="panel-title" style="font-size:18px;">📦 클릭 경로 Inventory 변화</div>';
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

    components.html(html, height=1060, scrolling=True)


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
        "label": inventory_changes.get("product_name", "Truck 이동 경로"),
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

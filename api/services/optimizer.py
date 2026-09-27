"""
Fuel Stop Optimizer using Dynamic Programming (DP) for cheapest stop selection.
"""
from typing import List, Dict, Any, Tuple, Optional


def optimize_fuel_stops(
    candidate_stations: List[Dict[str, Any]],
    route_distance_miles: float,
    tank_range_miles: float = 500.0,
    vehicle_mpg: float = 10.0
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[float], Optional[str]]:
    """
    Computes the optimal (cheapest) subset of fuel stations along the route such that
    no interval between consecutive fueling points exceeds `tank_range_miles`.

    Args:
        candidate_stations: List of candidate stations sorted by 'route_miles' ascending.
        route_distance_miles: Total route distance in miles.
        tank_range_miles: Maximum range on full tank (default 500.0).
        vehicle_mpg: Fuel economy in miles per gallon (default 10.0).

    Returns:
        (chosen_stops, total_cost_usd, error_message)
        - chosen_stops: List of stop dicts with stop details, gallons_purchased, and stop_cost_usd.
        - total_cost_usd: Total fuel cost in USD.
        - error_message: None if route is reachable, or descriptive string if unreachable.
    """
    if route_distance_miles <= 0:
        return [], 0.0, None

    # Case 1: Route is shorter than tank range -> 0 stops needed
    if route_distance_miles <= tank_range_miles:
        # Reaches destination on the initial full tank
        # Calculate nominal fuel cost using the cheapest available station along route if any, or 0.0
        return [], 0.0, None

    # Filter candidates to only those strictly within route bounds [0, route_distance_miles]
    valid_candidates = [
        s for s in candidate_stations
        if 0.0 < s['route_miles'] < route_distance_miles
    ]

    if not valid_candidates:
        return None, None, (
            f"Trip distance is {route_distance_miles:.1f} miles (exceeds {tank_range_miles:.0f} mi range), "
            f"but no fuel stations were found along the corridor."
        )

    # Nodes:
    # Index 0: Origin (mile = 0)
    # Index 1..N: Candidate stations
    # Index N+1: Destination (mile = route_distance_miles)
    n_candidates = len(valid_candidates)
    n_nodes = n_candidates + 2
    dest_idx = n_nodes - 1

    positions = [0.0] + [s['route_miles'] for s in valid_candidates] + [route_distance_miles]
    prices = [0.0] + [float(s['retail_price']) for s in valid_candidates] + [0.0]

    INF = float('inf')
    dp = [INF] * n_nodes
    prev = [-1] * n_nodes
    dp[0] = 0.0

    # DP forward pass
    for i in range(n_nodes - 1):
        if dp[i] == INF:
            continue
        
        pos_i = positions[i]

        for j in range(i + 1, n_nodes):
            pos_j = positions[j]
            gap = pos_j - pos_i

            if gap > tank_range_miles:
                # Since positions are sorted, further stations are also unreachable
                break

            gallons = gap / vehicle_mpg

            if j == dest_idx:
                # Final leg from station i to destination:
                # Fuel is purchased at station i
                if i == 0:
                    # Direct origin to destination (already handled, but for completeness)
                    cost = 0.0
                else:
                    cost = dp[i] + (gallons * prices[i])
            else:
                # Leg from node i to station j:
                # Fuel is purchased at station j
                cost = dp[i] + (gallons * prices[j])

            if cost < dp[j]:
                dp[j] = cost
                prev[j] = i

    # Check if destination was reachable
    if dp[dest_idx] == INF:
        # Identify the largest gap to provide a clear error message
        max_gap = 0.0
        gap_start, gap_end = 0.0, 0.0
        for k in range(len(positions) - 1):
            curr_gap = positions[k + 1] - positions[k]
            if curr_gap > max_gap:
                max_gap = curr_gap
                gap_start, gap_end = positions[k], positions[k + 1]

        return None, None, (
            f"Route cannot be completed with a {tank_range_miles:.0f}-mile vehicle range. "
            f"A gap of {max_gap:.1f} miles exists between mile {gap_start:.1f} and mile {gap_end:.1f} with no fuel stations."
        )

    # Path reconstruction
    path = []
    curr = dest_idx
    while curr != -1:
        path.append(curr)
        curr = prev[curr]
    path.reverse()

    # path looks like [0, stop_idx_1, stop_idx_2, ..., dest_idx]
    chosen_stop_indices = [idx for idx in path if 0 < idx < dest_idx]
    
    # Calculate gallons purchased and cost at each chosen stop
    chosen_stops: List[Dict[str, Any]] = []
    
    for step_num, node_idx in enumerate(chosen_stop_indices):
        station_data = valid_candidates[node_idx - 1].copy()
        
        # Determine the segment this station pays for:
        # 1. Incoming leg from previous stop (or origin)
        prev_node = path[step_num] # node before this stop
        incoming_gap = positions[node_idx] - positions[prev_node]
        gallons_bought = incoming_gap / vehicle_mpg
        
        # 2. If this is the LAST fuel stop, it also covers the remainder of the trip to destination
        is_last_stop = (step_num == len(chosen_stop_indices) - 1)
        if is_last_stop:
            final_gap = route_distance_miles - positions[node_idx]
            gallons_bought += (final_gap / vehicle_mpg)

        price = float(station_data['retail_price'])
        stop_cost = round(gallons_bought * price, 2)
        
        station_data['sequence'] = step_num + 1
        station_data['price_per_gal'] = price
        station_data['miles_from_start'] = round(station_data['route_miles'], 2)
        station_data['gallons_purchased'] = round(gallons_bought, 2)
        station_data['stop_cost_usd'] = stop_cost
        station_data['coordinates'] = [station_data['longitude'], station_data['latitude']]
        
        chosen_stops.append(station_data)

    total_cost_usd = round(sum(s['stop_cost_usd'] for s in chosen_stops), 2)

    return chosen_stops, total_cost_usd, None

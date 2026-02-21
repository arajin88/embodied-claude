"""Test: detect live events from Tapo C220."""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


async def main():
    import onvif
    from onvif import ONVIFCamera

    host = os.getenv("TAPO_CAMERA_HOST", "")
    port = int(os.getenv("TAPO_ONVIF_PORT", "2020"))
    username = os.getenv("TAPO_USERNAME", "")
    password = os.getenv("TAPO_PASSWORD", "")

    if not host or not username or not password:
        print("Error: Set TAPO_CAMERA_HOST, TAPO_USERNAME, TAPO_PASSWORD")
        sys.exit(1)

    onvif_dir = os.path.dirname(onvif.__file__)
    wsdl_dir = os.path.join(onvif_dir, "wsdl")

    cam = ONVIFCamera(
        host, port, username, password,
        wsdl_dir=wsdl_dir,
        adjust_time=True,
    )
    await cam.update_xaddrs()
    print(f"Connected to {host}")

    events_service = await cam.create_events_service()
    result = await events_service.CreatePullPointSubscription(
        {"InitialTerminationTime": "PT120S"}
    )
    sub_addr = result.SubscriptionReference.Address._value_1
    cam.xaddrs[
        "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"
    ] = sub_addr
    pullpoint = await cam.create_pullpoint_service()

    # Force the camera to send current state of all event properties
    print("Calling SetSynchronizationPoint...")
    try:
        await pullpoint.SetSynchronizationPoint()
        print("  OK - camera should now send initial state")
    except Exception as e:
        print(f"  SetSynchronizationPoint failed: {e}")

    print("\nListening for events (30 seconds)...")
    print("-" * 60)

    seen_events = []
    for i in range(10):
        try:
            messages = await pullpoint.PullMessages({
                "Timeout": "PT3S",
                "MessageLimit": 50,
            })
            if messages.NotificationMessage:
                for msg in messages.NotificationMessage:
                    topic = msg.Topic._value_1 if msg.Topic else "?"
                    # Short topic name
                    short = topic.split("/")[-1] if "/" in topic else topic
                    data_items = {}
                    ts = ""
                    if msg.Message and msg.Message._value_1:
                        d = msg.Message._value_1
                        ts = getattr(d, "UtcTime", "") or ""
                        if hasattr(d, "Source") and d.Source:
                            for item in (d.Source.SimpleItem or []):
                                data_items[f"src:{item.Name}"] = item.Value
                        if hasattr(d, "Data") and d.Data:
                            for item in (d.Data.SimpleItem or []):
                                data_items[item.Name] = item.Value
                    print(f"  {short:20s} {data_items}  ({ts})")
                    seen_events.append(topic)
            else:
                print(f"  ... (no events, pull #{i})")
        except Exception as e:
            print(f"  Error: {e}")
            break

    print("-" * 60)
    if seen_events:
        unique = set(seen_events)
        print(f"\n{len(seen_events)} events total, {len(unique)} unique topics:")
        for t in sorted(unique):
            count = seen_events.count(t)
            print(f"  [{count}x] {t}")
    else:
        print("No events detected.")

    try:
        sub = await cam.create_subscription_service("PullPointSubscription")
        await sub.Unsubscribe()
    except Exception:
        pass
    await cam.close()


if __name__ == "__main__":
    asyncio.run(main())

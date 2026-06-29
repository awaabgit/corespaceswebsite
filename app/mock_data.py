"""
Sample listings so the site runs standalone (no Zoho, no Supabase) on day one.
Image URLs point at a free placeholder service so it looks real out of the box.
These are replaced automatically the moment real data flows from Zoho/Supabase.
"""

MOCK_LISTINGS = [
    {
        "id": "1001",
        "slug": "marina-gate-2br-sea-view",
        "title": "2-Bedroom Apartment, Marina Gate",
        "type": "sale",
        "price": 2_650_000,
        "currency": "AED",
        "beds": 2,
        "baths": 3,
        "area_sqft": 1340,
        "location": "Dubai Marina",
        "community": "Marina Gate",
        "status": "available",
        "featured": True,
        "description": (
            "A bright, high-floor two-bedroom with uninterrupted sea views, floor-to-ceiling "
            "glazing and a wraparound balcony. Walk to the tram, the marina walk and JBR beach."
        ),
        "images": [
            "https://picsum.photos/seed/marina1/1200/800",
            "https://picsum.photos/seed/marina2/1200/800",
            "https://picsum.photos/seed/marina3/1200/800",
        ],
        "agent_name": "Sara Khalid",
        "agent_phone": "+971 50 000 0001",
    },
    {
        "id": "1002",
        "slug": "downtown-1br-burj-view",
        "title": "1-Bedroom, Burj Khalifa View",
        "type": "rent",
        "price": 145_000,
        "currency": "AED",
        "beds": 1,
        "baths": 2,
        "area_sqft": 820,
        "location": "Downtown Dubai",
        "community": "The Address Residences",
        "status": "available",
        "featured": True,
        "description": (
            "Serviced one-bedroom in the heart of Downtown with a direct Burj Khalifa view, "
            "hotel amenities and a five-minute walk to Dubai Mall. Let furnished or unfurnished."
        ),
        "images": [
            "https://picsum.photos/seed/downtown1/1200/800",
            "https://picsum.photos/seed/downtown2/1200/800",
        ],
        "agent_name": "Omar Rahman",
        "agent_phone": "+971 50 000 0002",
    },
    {
        "id": "1003",
        "slug": "arabian-ranches-4br-villa",
        "title": "4-Bedroom Villa, Arabian Ranches",
        "type": "sale",
        "price": 6_200_000,
        "currency": "AED",
        "beds": 4,
        "baths": 5,
        "area_sqft": 3950,
        "location": "Arabian Ranches",
        "community": "Palmera",
        "status": "available",
        "featured": True,
        "description": (
            "Single-row family villa backing onto landscaped parkland, with a private pool, "
            "maid's room and a two-car garage. Walking distance to the community school."
        ),
        "images": [
            "https://picsum.photos/seed/ranches1/1200/800",
            "https://picsum.photos/seed/ranches2/1200/800",
            "https://picsum.photos/seed/ranches3/1200/800",
        ],
        "agent_name": "Sara Khalid",
        "agent_phone": "+971 50 000 0001",
    },
    {
        "id": "1004",
        "slug": "business-bay-studio",
        "title": "Studio, Business Bay Canal",
        "type": "rent",
        "price": 72_000,
        "currency": "AED",
        "beds": 0,
        "baths": 1,
        "area_sqft": 480,
        "location": "Business Bay",
        "community": "Canal Residence",
        "status": "available",
        "featured": False,
        "description": (
            "Efficient canal-facing studio with a fitted kitchen and a shared pool and gym. "
            "Ideal first rental, minutes from the metro and the Downtown business district."
        ),
        "images": [
            "https://picsum.photos/seed/bay1/1200/800",
        ],
        "agent_name": "Omar Rahman",
        "agent_phone": "+971 50 000 0002",
    },
    {
        "id": "1005",
        "slug": "palm-jumeirah-penthouse",
        "title": "Penthouse, Palm Jumeirah",
        "type": "sale",
        "price": 18_500_000,
        "currency": "AED",
        "beds": 4,
        "baths": 6,
        "area_sqft": 6100,
        "location": "Palm Jumeirah",
        "community": "Shoreline",
        "status": "available",
        "featured": False,
        "description": (
            "Full-floor penthouse with a private rooftop terrace, plunge pool and panoramic "
            "views across the Gulf and the Dubai skyline. Two parking bays and beach access."
        ),
        "images": [
            "https://picsum.photos/seed/palm1/1200/800",
            "https://picsum.photos/seed/palm2/1200/800",
        ],
        "agent_name": "Sara Khalid",
        "agent_phone": "+971 50 000 0001",
    },
    {
        "id": "1006",
        "slug": "jvc-townhouse-3br",
        "title": "3-Bedroom Townhouse, JVC",
        "type": "sale",
        "price": 2_980_000,
        "currency": "AED",
        "beds": 3,
        "baths": 4,
        "area_sqft": 2100,
        "location": "Jumeirah Village Circle",
        "community": "District 12",
        "status": "available",
        "featured": False,
        "description": (
            "Corner townhouse with a private garden, rooftop terrace and a flexible ground-floor "
            "study. A well-priced family option in one of Dubai's fastest-growing communities."
        ),
        "images": [
            "https://picsum.photos/seed/jvc1/1200/800",
            "https://picsum.photos/seed/jvc2/1200/800",
        ],
        "agent_name": "Omar Rahman",
        "agent_phone": "+971 50 000 0002",
    },
]

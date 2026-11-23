"""HTTP route modules. Each ``register_routes`` adds its routes directly to the app.

Routes are registered on the app (not through ``include_router``) so the app keeps
``main.lifespan`` as its lifespan context unchanged.
"""

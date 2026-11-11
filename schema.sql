/* =====================================================================
   Experience Booking Recommender - SQL Server schema (proposed)
   Part 1: proposed production catalog (independent reference design)
   Part 2: interaction signals (what the recommender learns from)
   Part 3: recommender output + tracking (what the app reads)
   ===================================================================== */

/* ---------------- Part 1: Core catalog ---------------- */

CREATE TABLE dbo.Users (
    UserId          BIGINT IDENTITY PRIMARY KEY,
    CreatedAt       DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    Country         NVARCHAR(2)    NULL,      -- e.g. KW, LB
    City            NVARCHAR(100)  NULL,
    Gender          CHAR(1)        NULL,
    BirthYear       SMALLINT       NULL,
    PreferredLang   NVARCHAR(5)    NULL,
    IsGuest         BIT            NOT NULL DEFAULT 0
);

CREATE TABLE dbo.Categories (
    CategoryId      INT IDENTITY PRIMARY KEY,
    ParentId        INT NULL REFERENCES dbo.Categories(CategoryId),
    Code            NVARCHAR(50)   NOT NULL UNIQUE, -- chalet, farm, desert_tent, jakhour, atv, skydiving, scuba, restaurant, market_product
    NameEn          NVARCHAR(100)  NOT NULL,
    NameAr          NVARCHAR(100)  NULL,
    Vertical        NVARCHAR(20)   NOT NULL         -- stay | activity | food | product
        CHECK (Vertical IN ('stay','activity','food','product'))
);

CREATE TABLE dbo.Vendors (
    VendorId        BIGINT IDENTITY PRIMARY KEY,
    Name            NVARCHAR(200)  NOT NULL,
    City            NVARCHAR(100)  NULL,
    IsActive        BIT            NOT NULL DEFAULT 1
);

CREATE TABLE dbo.Listings (                       -- any bookable/orderable item
    ListingId       BIGINT IDENTITY PRIMARY KEY,
    VendorId        BIGINT         NOT NULL REFERENCES dbo.Vendors(VendorId),
    CategoryId      INT            NOT NULL REFERENCES dbo.Categories(CategoryId),
    Title           NVARCHAR(200)  NOT NULL,
    Description     NVARCHAR(MAX)  NULL,
    City            NVARCHAR(100)  NULL,
    Latitude        DECIMAL(9,6)   NULL,
    Longitude       DECIMAL(9,6)   NULL,
    BasePrice       DECIMAL(10,3)  NULL,
    Currency        CHAR(3)        NOT NULL DEFAULT 'KWD',
    Capacity        INT            NULL,          -- guests (stays/activities)
    AvgRating       DECIMAL(3,2)   NULL,          -- denormalised for speed
    RatingCount     INT            NOT NULL DEFAULT 0,
    IsActive        BIT            NOT NULL DEFAULT 1,
    CreatedAt       DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_Listings_Category ON dbo.Listings(CategoryId, IsActive);

CREATE TABLE dbo.Tags (
    TagId           INT IDENTITY PRIMARY KEY,
    Name            NVARCHAR(50)   NOT NULL UNIQUE  -- pool, sea_view, family, kids_friendly, bbq, vegan...
);

CREATE TABLE dbo.ListingTags (                    -- content features for cold start
    ListingId       BIGINT NOT NULL REFERENCES dbo.Listings(ListingId),
    TagId           INT    NOT NULL REFERENCES dbo.Tags(TagId),
    PRIMARY KEY (ListingId, TagId)
);

/* ---------------- Part 2: Interaction signals ---------------- */

CREATE TABLE dbo.Bookings (                       -- stays + activities
    BookingId       BIGINT IDENTITY PRIMARY KEY,
    UserId          BIGINT    NOT NULL REFERENCES dbo.Users(UserId),
    ListingId       BIGINT    NOT NULL REFERENCES dbo.Listings(ListingId),
    CheckIn         DATE      NOT NULL,
    CheckOut        DATE      NULL,
    Guests          INT       NULL,
    TotalPrice      DECIMAL(10,3) NOT NULL,
    Status          NVARCHAR(20)  NOT NULL        -- confirmed | completed | cancelled
        CHECK (Status IN ('pending','confirmed','completed','cancelled')),
    CreatedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_Bookings_User ON dbo.Bookings(UserId, CreatedAt);
CREATE INDEX IX_Bookings_Listing ON dbo.Bookings(ListingId);

CREATE TABLE dbo.Orders (                         -- food + market products
    OrderId         BIGINT IDENTITY PRIMARY KEY,
    UserId          BIGINT    NOT NULL REFERENCES dbo.Users(UserId),
    VendorId        BIGINT    NOT NULL REFERENCES dbo.Vendors(VendorId),
    TotalPrice      DECIMAL(10,3) NOT NULL,
    Status          NVARCHAR(20)  NOT NULL,
    CreatedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.OrderItems (
    OrderItemId     BIGINT IDENTITY PRIMARY KEY,
    OrderId         BIGINT NOT NULL REFERENCES dbo.Orders(OrderId),
    ListingId       BIGINT NOT NULL REFERENCES dbo.Listings(ListingId),
    Quantity        INT    NOT NULL DEFAULT 1,
    UnitPrice       DECIMAL(10,3) NOT NULL
);
CREATE INDEX IX_OrderItems_Listing ON dbo.OrderItems(ListingId);

CREATE TABLE dbo.Favourites (
    UserId          BIGINT    NOT NULL REFERENCES dbo.Users(UserId),
    ListingId       BIGINT    NOT NULL REFERENCES dbo.Listings(ListingId),
    CreatedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    RemovedAt       DATETIME2 NULL,               -- retain removal history; inactive favourites are not positives
    PRIMARY KEY (UserId, ListingId)
);

CREATE TABLE dbo.Reviews (
    ReviewId        BIGINT IDENTITY PRIMARY KEY,
    UserId          BIGINT    NOT NULL REFERENCES dbo.Users(UserId),
    ListingId       BIGINT    NOT NULL REFERENCES dbo.Listings(ListingId),
    BookingId       BIGINT    NULL REFERENCES dbo.Bookings(BookingId),
    Rating          TINYINT   NOT NULL CHECK (Rating BETWEEN 1 AND 5),
    Comment         NVARCHAR(2000) NULL,
    CreatedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_Reviews_Listing ON dbo.Reviews(ListingId);

CREATE TABLE dbo.UserEvents (                     -- high-volume behaviour log
    EventId         BIGINT IDENTITY PRIMARY KEY,
    UserId          BIGINT       NULL,            -- NULL for guests
    SessionId       UNIQUEIDENTIFIER NOT NULL,
    EventType       NVARCHAR(30) NOT NULL         -- view | click | share | add_to_cart | reco_impression | reco_click
        CHECK (EventType IN ('view','click','share','add_to_cart','reco_impression','reco_click')),
    ListingId       BIGINT       NULL REFERENCES dbo.Listings(ListingId),
    CategoryId      INT          NULL REFERENCES dbo.Categories(CategoryId),
    Source          NVARCHAR(30) NULL,            -- home_more_for_you | search | category_page | similar_items
    DurationMs      INT          NULL,            -- time on listing page
    CreatedAt       DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_UserEvents_User ON dbo.UserEvents(UserId, CreatedAt) INCLUDE (EventType, ListingId);
CREATE INDEX IX_UserEvents_Listing ON dbo.UserEvents(ListingId, EventType);

CREATE TABLE dbo.Searches (
    SearchId        BIGINT IDENTITY PRIMARY KEY,
    UserId          BIGINT        NULL,
    SessionId       UNIQUEIDENTIFIER NOT NULL,
    QueryText       NVARCHAR(200) NULL,
    CategoryId      INT           NULL REFERENCES dbo.Categories(CategoryId),
    City            NVARCHAR(100) NULL,
    DateFrom        DATE          NULL,
    DateTo          DATE          NULL,
    Guests          INT           NULL,
    PriceMin        DECIMAL(10,3) NULL,
    PriceMax        DECIMAL(10,3) NULL,
    ResultCount     INT           NULL,
    ClickedListingId BIGINT       NULL REFERENCES dbo.Listings(ListingId),
    CreatedAt       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------------- Part 3: Recommender output + tracking ---------------- */
GO
CREATE SCHEMA reco;

-- Unified training view: one weighted row per user-listing signal
GO
CREATE VIEW reco.vInteractions AS
SELECT UserId, ListingId, 'booking'  AS Signal, 5.0 AS Weight, CreatedAt FROM dbo.Bookings  WHERE Status IN ('confirmed','completed')
UNION ALL
SELECT o.UserId, oi.ListingId, 'order', 4.0, o.CreatedAt FROM dbo.Orders o JOIN dbo.OrderItems oi ON oi.OrderId = o.OrderId WHERE o.Status IN ('confirmed','completed')
UNION ALL
SELECT UserId, ListingId, 'favourite', 3.0, CreatedAt FROM dbo.Favourites WHERE RemovedAt IS NULL
UNION ALL
SELECT UserId, ListingId, 'review', CAST(Rating - 3 AS FLOAT), CreatedAt FROM dbo.Reviews   -- 1-2 stars negative
UNION ALL
SELECT UserId, ListingId, EventType, CASE EventType WHEN 'add_to_cart' THEN 2.0 WHEN 'click' THEN 1.0 ELSE 0.5 END, CreatedAt
FROM dbo.UserEvents WHERE UserId IS NOT NULL AND ListingId IS NOT NULL AND EventType IN ('view','click','add_to_cart');
GO

-- Precomputed per-user, per-category recommendations (written by the Python service nightly)
CREATE TABLE reco.UserRecommendations (
    UserId          BIGINT       NOT NULL,
    CategoryId      INT          NOT NULL,
    Rank            SMALLINT     NOT NULL,
    ListingId       BIGINT       NOT NULL,
    Score           FLOAT        NOT NULL,
    Reason          NVARCHAR(50) NULL,            -- because_you_booked | popular_near_you | similar_to_favourite
    ModelVersion    NVARCHAR(30) NOT NULL,
    GeneratedAt     DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY (UserId, CategoryId, Rank)
);

-- "Similar to this" item-to-item lists, per category
CREATE TABLE reco.SimilarListings (
    ListingId        BIGINT   NOT NULL,
    SimilarListingId BIGINT   NOT NULL,
    Rank             SMALLINT NOT NULL,
    Score            FLOAT    NOT NULL,
    ModelVersion     NVARCHAR(30) NOT NULL,
    PRIMARY KEY (ListingId, Rank)
);

-- Fallback for guests and new users: trending per category and city
CREATE TABLE reco.PopularListings (
    CategoryId      INT          NOT NULL,
    City            NVARCHAR(100) NOT NULL DEFAULT '',
    Rank            SMALLINT     NOT NULL,
    ListingId       BIGINT       NOT NULL,
    Score           FLOAT        NOT NULL,
    GeneratedAt     DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY (CategoryId, City, Rank)
);

-- Model runs, for monitoring and A/B comparison
CREATE TABLE reco.ModelRuns (
    RunId           INT IDENTITY PRIMARY KEY,
    ModelVersion    NVARCHAR(30) NOT NULL,
    CategoryId      INT          NULL,
    Algorithm       NVARCHAR(50) NOT NULL,        -- implicit_als | lightfm | item_knn | popularity
    PrecisionAt10   FLOAT NULL,
    RecallAt10      FLOAT NULL,
    NdcgAt10        FLOAT NULL,
    TrainedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
